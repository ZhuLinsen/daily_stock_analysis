# -*- coding: utf-8 -*-
"""Portfolio and watchlist alert helpers for Alert Center P6."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Dict, Iterable, List, Optional

from src.services.portfolio_risk_service import PortfolioRiskService
from src.services.portfolio_service import PortfolioService


logger = logging.getLogger(__name__)

SYMBOL_BATCH_TARGET_SCOPES = frozenset({"watchlist", "portfolio_holdings"})
PORTFOLIO_TARGET_SCOPES = frozenset({"portfolio_holdings", "portfolio_account"})
PORTFOLIO_ALERT_TYPES = frozenset({
    "portfolio_stop_loss",
    "portfolio_concentration",
    "portfolio_drawdown",
    "portfolio_price_stale",
})

EXPANDED_TARGET_SOFT_CAP = 100
TARGET_RESULTS_LIMIT = 20
DRY_RUN_TARGET_TIMEOUT_SECONDS = 10
DRY_RUN_TOTAL_TIMEOUT_SECONDS = 30


@dataclass(frozen=True)
class ExpandedSymbolTarget:
    """A concrete symbol produced from a parent batch rule."""

    symbol: str
    display_target: str


@dataclass(frozen=True)
class RuntimeAlertPayload:
    """Runtime rule plus the identity used for cooldown/history."""

    key: str
    rule: Any
    effective_target: str
    display_target: str


@dataclass
class PortfolioRiskAlert:
    """Runtime alert for account-level portfolio risk rules."""

    target_scope: str
    target: str
    alert_type: str
    parameters: Dict[str, Any]
    metadata: Dict[str, Any] = field(default_factory=dict)
    description: str = ""
    stock_code: str = ""

    def __post_init__(self) -> None:
        effective_target = self.metadata.get("effective_target") or portfolio_effective_target(self.target)
        self.stock_code = str(effective_target)


@dataclass
class StaticAlertEvaluation:
    """Runtime placeholder for skipped/degraded expansion results."""

    stock_code: str
    alert_type: str
    message: str
    record_status: str = "skipped"
    metadata: Dict[str, Any] = field(default_factory=dict)
    description: str = ""


def normalize_portfolio_alert_parameters(alert_type: str, parameters: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize P6 portfolio alert parameters."""

    if alert_type not in PORTFOLIO_ALERT_TYPES:
        raise ValueError(f"unsupported portfolio alert_type: {alert_type}")
    if not isinstance(parameters, dict):
        raise ValueError("parameters must be an object")

    if alert_type == "portfolio_stop_loss":
        mode = str(parameters.get("mode") or "near").strip().lower()
        if mode not in {"near", "breach"}:
            raise ValueError("portfolio_stop_loss mode must be near or breach")
        return {"mode": mode}

    return {}


def portfolio_effective_target(target: str) -> str:
    target_text = str(target or "all").strip() or "all"
    return "account:all" if target_text == "all" else f"account:{target_text}"


def normalize_batch_target_scope_target(target_scope: str, target: str) -> str:
    target_text = str(target or "").strip()
    if target_scope == "watchlist":
        if target_text not in {"", "default"}:
            raise ValueError("watchlist target must be default")
        return "default"
    if target_scope in PORTFOLIO_TARGET_SCOPES:
        if target_text == "all":
            return "all"
        return str(_positive_int_target(target_text))
    return target_text


def ensure_active_portfolio_account(target: str, *, portfolio_service: Optional[PortfolioService] = None) -> None:
    """Validate that an explicit portfolio account target exists and is active."""

    if str(target or "").strip() == "all":
        return
    account_id = _positive_int_target(target)
    service = portfolio_service or PortfolioService()
    accounts = service.list_accounts(include_inactive=False)
    active_ids = {int(item.get("id")) for item in accounts if item.get("id") is not None}
    if account_id not in active_ids:
        raise ValueError(f"portfolio account is not active or does not exist: {account_id}")


def expand_symbol_targets(
    *,
    target_scope: str,
    target: str,
    config: Any,
    portfolio_service: Optional[PortfolioService] = None,
) -> tuple[List[ExpandedSymbolTarget], int]:
    """Expand watchlist or portfolio holdings into concrete, de-duplicated symbols.

    Returns ``(targets, overflow_count)``. The returned targets are already capped
    by ``EXPANDED_TARGET_SOFT_CAP``.
    """

    if target_scope == "watchlist":
        symbols = _watchlist_symbols(config)
        display_prefix = "自选股"
    elif target_scope == "portfolio_holdings":
        symbols = _portfolio_holding_symbols(target=target, portfolio_service=portfolio_service)
        display_prefix = "持仓"
    else:
        return [], 0

    unique = _dedupe_symbols(symbols)
    overflow_count = max(0, len(unique) - EXPANDED_TARGET_SOFT_CAP)
    capped = unique[:EXPANDED_TARGET_SOFT_CAP]
    return [
        ExpandedSymbolTarget(symbol=symbol, display_target=f"{display_prefix} - {symbol}")
        for symbol in capped
    ], overflow_count


def make_static_payload(
    *,
    parent_key: str,
    rule_id: int,
    alert_type: str,
    effective_target: str,
    display_target: str,
    message: str,
    record_status: str = "skipped",
) -> RuntimeAlertPayload:
    rule = StaticAlertEvaluation(
        stock_code=effective_target,
        alert_type=alert_type,
        message=message,
        record_status=record_status,
        metadata={
            "persisted_rule_id": rule_id,
            "effective_target": effective_target,
            "display_target": display_target,
        },
        description=message,
    )
    return RuntimeAlertPayload(
        key=f"{parent_key}|{effective_target}",
        rule=rule,
        effective_target=effective_target,
        display_target=display_target,
    )


def make_portfolio_risk_payload(
    *,
    parent_key: str,
    data: Dict[str, Any],
) -> RuntimeAlertPayload:
    effective_target = portfolio_effective_target(data["target"])
    display_target = "全部账户" if data["target"] == "all" else f"账户 {data['target']}"
    rule = PortfolioRiskAlert(
        target_scope=data["target_scope"],
        target=data["target"],
        alert_type=data["alert_type"],
        parameters=dict(data.get("parameters") or {}),
        metadata={
            "persisted_rule_id": data["id"],
            "effective_target": effective_target,
            "display_target": display_target,
        },
        description=data.get("name") or data["alert_type"],
    )
    return RuntimeAlertPayload(
        key=f"{parent_key}|{effective_target}",
        rule=rule,
        effective_target=effective_target,
        display_target=display_target,
    )


def evaluate_static_alert(rule: StaticAlertEvaluation) -> Dict[str, Any]:
    return {
        "rule_id": int(rule.metadata.get("persisted_rule_id", 0) or 0),
        "status": "not_triggered",
        "record_status": rule.record_status,
        "triggered": False,
        "observed_value": None,
        "threshold": None,
        "data_source": None,
        "data_timestamp": None,
        "reason": rule.message,
        "message": rule.message,
    }


def evaluate_portfolio_risk_alert(
    rule: PortfolioRiskAlert,
    *,
    portfolio_service: Optional[PortfolioService] = None,
    risk_service: Optional[PortfolioRiskService] = None,
) -> Dict[str, Any]:
    """Evaluate an account-level portfolio alert."""

    account_id = None if rule.target == "all" else _positive_int_target(rule.target)
    service = portfolio_service or PortfolioService()
    risk = risk_service or PortfolioRiskService(portfolio_service=service)

    if rule.alert_type == "portfolio_price_stale":
        snapshot = service.get_portfolio_snapshot(account_id=account_id, cost_method="fifo")
        return _evaluate_price_stale(rule, snapshot)

    report = risk.get_risk_report(account_id=account_id, cost_method="fifo")
    if rule.alert_type == "portfolio_stop_loss":
        return _evaluate_stop_loss(rule, report)
    if rule.alert_type == "portfolio_concentration":
        return _evaluate_concentration(rule, report)
    if rule.alert_type == "portfolio_drawdown":
        return _evaluate_drawdown(rule, report)

    return _portfolio_result(
        rule,
        triggered=False,
        observed_value=None,
        threshold=None,
        message=f"unsupported portfolio alert_type: {rule.alert_type}",
        record_status="failed",
        diagnostics={"error": "unsupported_portfolio_alert_type"},
    )


def result_to_target_result(payload: RuntimeAlertPayload, result: Dict[str, Any]) -> Dict[str, Any]:
    record_status = result.get("record_status")
    return {
        "target": payload.effective_target,
        "display_target": payload.display_target,
        "status": result.get("status") or "evaluation_error",
        "record_status": record_status,
        "triggered": bool(result.get("triggered")),
        "observed_value": result.get("observed_value"),
        "threshold": result.get("threshold"),
        "message": result.get("message") or result.get("reason") or "",
    }


def aggregate_dry_run_results(rule_id: int, target_scope: str, results: List[Dict[str, Any]]) -> Dict[str, Any]:
    target_results = sorted(
        results,
        key=lambda item: (
            0 if item.get("triggered") else 1,
            0 if item.get("record_status") in {"degraded", "failed"} else 1,
            str(item.get("target") or ""),
        ),
    )
    visible_results = target_results[:TARGET_RESULTS_LIMIT]
    triggered_count = sum(1 for item in target_results if item.get("triggered"))
    degraded_count = sum(1 for item in target_results if item.get("record_status") == "degraded")
    skipped_count = sum(1 for item in target_results if item.get("record_status") == "skipped")
    failed_count = sum(1 for item in target_results if item.get("record_status") == "failed")
    successful_count = sum(
        1
        for item in target_results
        if item.get("record_status") not in {"failed"} and item.get("status") != "evaluation_error"
    )

    if triggered_count:
        status = "triggered"
        triggered = True
    elif successful_count or skipped_count or degraded_count:
        status = "not_triggered"
        triggered = False
    else:
        status = "evaluation_error"
        triggered = False

    if not target_results:
        status = "evaluation_error"
        triggered = False
        message = "No targets were evaluated"
    else:
        message = (
            f"Evaluated {len(target_results)} targets: "
            f"{triggered_count} triggered, {degraded_count} degraded, "
            f"{skipped_count} skipped, {failed_count} failed"
        )

    first_observed = next((item.get("observed_value") for item in target_results if item.get("observed_value") is not None), None)
    return {
        "rule_id": rule_id,
        "target_scope": target_scope,
        "status": status,
        "triggered": triggered,
        "observed_value": first_observed,
        "message": message,
        "evaluated_count": len(target_results),
        "triggered_count": triggered_count,
        "degraded_count": degraded_count,
        "skipped_count": skipped_count,
        "target_results": visible_results,
    }


def _watchlist_symbols(config: Any) -> List[str]:
    refresh = getattr(config, "refresh_stock_list", None)
    if callable(refresh):
        try:
            refresh()
        except Exception as exc:
            logger.warning("[portfolio_alerts] Failed to refresh watchlist symbols: %s", exc)
    return list(getattr(config, "stock_list", []) or [])


def _portfolio_holding_symbols(
    *,
    target: str,
    portfolio_service: Optional[PortfolioService],
) -> List[str]:
    service = portfolio_service or PortfolioService()
    account_id = None if target == "all" else _positive_int_target(target)
    snapshot = service.get_portfolio_snapshot(account_id=account_id, cost_method="fifo")
    symbols: List[str] = []
    for account in snapshot.get("accounts", []) or []:
        for position in account.get("positions", []) or []:
            try:
                quantity = float(position.get("quantity") or 0.0)
            except (TypeError, ValueError):
                quantity = 0.0
            if quantity <= 0:
                continue
            symbol = _normalize_symbol(position.get("symbol"))
            if symbol:
                symbols.append(symbol)
    return symbols


def _dedupe_symbols(symbols: Iterable[Any]) -> List[str]:
    output: List[str] = []
    seen = set()
    for raw in symbols:
        symbol = _normalize_symbol(raw)
        if not symbol or symbol in seen:
            continue
        output.append(symbol)
        seen.add(symbol)
    return output


def _normalize_symbol(value: Any) -> str:
    return PortfolioService._normalize_symbol(str(value or ""))


def _positive_int_target(value: Any) -> int:
    try:
        account_id = int(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise ValueError("portfolio target must be all or a positive account id") from exc
    if account_id <= 0:
        raise ValueError("portfolio target must be all or a positive account id")
    return account_id


def _evaluate_stop_loss(rule: PortfolioRiskAlert, report: Dict[str, Any]) -> Dict[str, Any]:
    mode = str(rule.parameters.get("mode") or "near")
    stop_loss = report.get("stop_loss") or {}
    items = list(stop_loss.get("items") or [])
    if mode == "breach":
        affected = [item for item in items if bool(item.get("is_triggered"))]
        triggered = bool(affected)
    else:
        affected = items
        triggered = bool(stop_loss.get("near_alert")) and bool(affected)

    threshold_key = "stop_loss_alert_pct" if mode == "breach" else "stop_loss_near_ratio"
    threshold = _threshold(report, threshold_key)
    if mode == "near":
        stop_loss_pct = _threshold(report, "stop_loss_alert_pct") or 0.0
        near_ratio = _threshold(report, "stop_loss_near_ratio") or 0.0
        threshold = stop_loss_pct * near_ratio

    observed = max((float(item.get("loss_pct") or 0.0) for item in affected), default=0.0)
    diagnostics = _base_diagnostics(report, top_items=affected[:5])
    diagnostics.update({
        "mode": mode,
        "near_count": stop_loss.get("near_count", 0),
        "triggered_count": stop_loss.get("triggered_count", 0),
    })
    message = (
        f"{_display_account(report)} stop-loss {mode}: {len(affected)} affected symbols"
        if triggered
        else f"{_display_account(report)} stop-loss {mode}: no affected symbols"
    )
    return _portfolio_result(
        rule,
        triggered=triggered,
        observed_value=observed,
        threshold=threshold,
        message=message,
        diagnostics=diagnostics,
    )


def _evaluate_concentration(rule: PortfolioRiskAlert, report: Dict[str, Any]) -> Dict[str, Any]:
    concentration = report.get("concentration") or {}
    observed = float(concentration.get("top_weight_pct") or 0.0)
    threshold = _threshold(report, "concentration_alert_pct")
    triggered = bool(concentration.get("alert"))
    diagnostics = _base_diagnostics(report, top_items=concentration.get("top_positions") or [])
    diagnostics.update({
        "total_market_value": concentration.get("total_market_value"),
        "top_weight_pct": observed,
    })
    message = f"{_display_account(report)} concentration top weight {observed:.2f}%"
    return _portfolio_result(
        rule,
        triggered=triggered,
        observed_value=observed,
        threshold=threshold,
        message=message,
        diagnostics=diagnostics,
    )


def _evaluate_drawdown(rule: PortfolioRiskAlert, report: Dict[str, Any]) -> Dict[str, Any]:
    drawdown = report.get("drawdown") or {}
    observed = float(drawdown.get("max_drawdown_pct") or 0.0)
    threshold = _threshold(report, "drawdown_alert_pct")
    triggered = bool(drawdown.get("alert"))
    diagnostics = _base_diagnostics(report)
    diagnostics.update({
        "series_points": drawdown.get("series_points"),
        "current_drawdown_pct": drawdown.get("current_drawdown_pct"),
        "max_drawdown_pct": observed,
        "fx_stale": bool(drawdown.get("fx_stale")),
    })
    message = f"{_display_account(report)} max drawdown {observed:.2f}%"
    return _portfolio_result(
        rule,
        triggered=triggered,
        observed_value=observed,
        threshold=threshold,
        message=message,
        diagnostics=diagnostics,
    )


def _evaluate_price_stale(rule: PortfolioRiskAlert, snapshot: Dict[str, Any]) -> Dict[str, Any]:
    affected: List[Dict[str, Any]] = []
    for account in snapshot.get("accounts", []) or []:
        for position in account.get("positions", []) or []:
            if bool(position.get("price_stale")) or not bool(position.get("price_available", True)):
                affected.append({
                    "account_id": account.get("account_id"),
                    "symbol": position.get("symbol"),
                    "price_stale": bool(position.get("price_stale")),
                    "price_available": bool(position.get("price_available")),
                    "price_source": position.get("price_source"),
                    "price_date": position.get("price_date"),
                })

    diagnostics = _base_diagnostics_from_snapshot(snapshot, top_items=affected[:5])
    observed = float(len(affected))
    message = (
        f"{_display_snapshot_account(snapshot)} stale or missing prices: {len(affected)} symbols"
        if affected
        else f"{_display_snapshot_account(snapshot)} prices are current"
    )
    return _portfolio_result(
        rule,
        triggered=bool(affected),
        observed_value=observed,
        threshold=0.0,
        message=message,
        diagnostics=diagnostics,
        data_timestamp=_parse_date(snapshot.get("as_of")),
        data_source="portfolio_snapshot",
    )


def _portfolio_result(
    rule: PortfolioRiskAlert,
    *,
    triggered: bool,
    observed_value: Optional[float],
    threshold: Optional[float],
    message: str,
    diagnostics: Dict[str, Any],
    record_status: Optional[str] = None,
    data_timestamp: Optional[datetime] = None,
    data_source: str = "portfolio_risk",
) -> Dict[str, Any]:
    if data_timestamp is None:
        data_timestamp = _parse_date(diagnostics.get("as_of"))
    status = "triggered" if triggered else "not_triggered"
    return {
        "rule_id": int(rule.metadata.get("persisted_rule_id", 0) or 0),
        "status": status,
        "record_status": "triggered" if triggered else record_status,
        "triggered": triggered,
        "observed_value": observed_value,
        "threshold": threshold,
        "data_source": data_source,
        "data_timestamp": data_timestamp,
        "reason": message,
        "message": message,
        "diagnostics": json.dumps(diagnostics, ensure_ascii=False, sort_keys=True),
    }


def _base_diagnostics(report: Dict[str, Any], *, top_items: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    return {
        "account_id": report.get("account_id") if report.get("account_id") is not None else "all",
        "currency": report.get("currency"),
        "as_of": report.get("as_of"),
        "price_stale": False,
        "fx_stale": bool((report.get("drawdown") or {}).get("fx_stale")),
        "data_available": True,
        "top_affected_symbols": _top_symbols(top_items or []),
    }


def _base_diagnostics_from_snapshot(
    snapshot: Dict[str, Any],
    *,
    top_items: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    accounts = snapshot.get("accounts", []) or []
    explicit_account = accounts[0].get("account_id") if len(accounts) == 1 else "all"
    affected = top_items or []
    return {
        "account_id": explicit_account,
        "currency": snapshot.get("currency"),
        "as_of": snapshot.get("as_of"),
        "price_stale": any(bool(item.get("price_stale")) for item in affected),
        "fx_stale": bool(snapshot.get("fx_stale")),
        "data_available": all(bool(item.get("price_available")) for item in affected) if affected else True,
        "top_affected_symbols": _top_symbols(affected),
    }


def _top_symbols(items: List[Dict[str, Any]]) -> List[str]:
    output: List[str] = []
    for item in items[:5]:
        symbol = str(item.get("symbol") or "").strip()
        if symbol:
            output.append(symbol)
    return output


def _threshold(report: Dict[str, Any], name: str) -> Optional[float]:
    thresholds = report.get("thresholds") or {}
    value = thresholds.get(name)
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _display_account(report: Dict[str, Any]) -> str:
    account_id = report.get("account_id")
    return "account all" if account_id is None else f"account {account_id}"


def _display_snapshot_account(snapshot: Dict[str, Any]) -> str:
    accounts = snapshot.get("accounts", []) or []
    if len(accounts) == 1:
        return f"account {accounts[0].get('account_id')}"
    return "account all"


def _parse_date(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time())
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None
