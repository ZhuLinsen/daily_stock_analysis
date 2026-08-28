# -*- coding: utf-8 -*-
"""Virtual trader API endpoints."""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Security
from fastapi.security import APIKeyCookie

from api.v1.schemas.common import ErrorResponse
from api.v1.schemas.virtual_trader import (
    VirtualTraderAccountResponse,
    VirtualTraderEquityCurveResponse,
    VirtualTraderEquityPoint,
    VirtualTraderPositionItem,
    VirtualTraderPredictionItem,
    VirtualTraderPredictionListResponse,
    VirtualTraderResetRequest,
    VirtualTraderResetResponse,
    VirtualTraderRunRequest,
    VirtualTraderRunResponse,
    VirtualTraderStatsResponse,
    VirtualTraderTradeItem,
    VirtualTraderTradeListResponse,
)
from src.auth import COOKIE_NAME
from src.config import get_config
from src.core.trading_calendar import get_effective_trading_date
from src.repositories.virtual_trader_repo import VirtualTraderRepository
from src.services.virtual_trader.runner import VirtualTraderRunner
from src.services.virtual_trader.service import VirtualTraderService

logger = logging.getLogger(__name__)

admin_session_cookie = APIKeyCookie(name=COOKIE_NAME, scheme_name="AdminSessionCookie", auto_error=False)
router = APIRouter(dependencies=[Security(admin_session_cookie)])

AUTH_RESPONSE = {
    401: {"model": ErrorResponse, "description": "未登录或管理员会话无效（ADMIN_AUTH_ENABLED=true 时）"},
}


def _bad_request(exc: Exception) -> HTTPException:
    return HTTPException(status_code=400, detail={"error": "validation_error", "message": str(exc)})


def _internal_error(message: str, exc: Exception) -> HTTPException:
    logger.error("%s: %s", message, exc, exc_info=True)
    return HTTPException(status_code=500, detail={"error": "internal_error", "message": message})


def _build_runner() -> VirtualTraderRunner:
    config = get_config()
    repo = VirtualTraderRepository()
    service = VirtualTraderService(
        repo=repo,
        fx_usd_cny=getattr(config, "virtual_trader_fx_usd_cny", 7.2),
        fx_hkd_cny=getattr(config, "virtual_trader_fx_hkd_cny", 0.92),
        initial_cash_cny=getattr(config, "virtual_trader_initial_cash_cny", 1_000_000.0),
        cash_reserve_pct=getattr(config, "virtual_trader_cash_reserve_pct", 30.0),
        max_position_pct=getattr(config, "virtual_trader_max_position_pct", 15.0),
        stop_loss_pct=getattr(config, "virtual_trader_stop_loss_pct", 8.0),
    )
    return VirtualTraderRunner(service=service, repo=repo, config=config)


def _iso(value) -> Optional[str]:
    return value.isoformat() if value is not None else None


@router.get(
    "/account",
    response_model=VirtualTraderAccountResponse,
    responses={**AUTH_RESPONSE, 500: {"model": ErrorResponse}},
    summary="查询虚拟账户与当前持仓（含最新估值）",
)
def get_account() -> VirtualTraderAccountResponse:
    runner = _build_runner()
    try:
        repo = runner.repo
        account = repo.get_account()
        if account is None:
            return VirtualTraderAccountResponse(
                account_id=0,
                name="default",
                status="not_seeded",
                initial_cash_cny=runner.service.initial_cash_cny,
                cash_cny=0.0,
                cash_hkd=0.0,
                cash_usd=0.0,
                cash_total_cny=0.0,
                positions=[],
                positions_value_cny=0.0,
                total_value_cny=0.0,
                total_return_pct=0.0,
            )
        positions = []
        positions_value_cny = 0.0
        # 估值价优先取最近一次快照的收盘价映射，避免查询接口隐式发起网络请求
        snapshot = repo.get_latest_snapshot(account.id)
        snap_prices: dict = {}
        if snapshot and snapshot.positions_value_json:
            try:
                import json as _json

                snap_prices = _json.loads(snapshot.positions_value_json) or {}
            except Exception:
                snap_prices = {}
        for p in repo.list_open_positions(account.id):
            cached = snap_prices.get(p.stock_code) or {}
            last_price = cached.get("last_price")
            value = p.quantity * last_price if last_price else p.quantity * p.avg_cost
            value_cny = value * runner.service.fx_to_cny(p.currency)
            positions_value_cny += value_cny
            pnl_pct = None
            if last_price and p.avg_cost:
                pnl_pct = round((last_price - p.avg_cost) / p.avg_cost * 100.0, 2)
            positions.append(VirtualTraderPositionItem(
                id=p.id,
                stock_code=p.stock_code,
                name=p.name,
                market=p.market,
                currency=p.currency,
                quantity=p.quantity,
                avg_cost=round(p.avg_cost, 4),
                last_price=round(last_price, 4) if last_price else None,
                market_value=round(value, 2),
                market_value_cny=round(value_cny, 2),
                unrealized_pnl_pct=pnl_pct,
                realized_pnl=round(p.realized_pnl or 0.0, 2),
                status=p.status,
                opened_at=_iso(p.opened_at),
            ))
        cash_total_cny = (
            account.cash_cny
            + account.cash_hkd * runner.service.fx_hkd_cny
            + account.cash_usd * runner.service.fx_usd_cny
        )
        total_value = cash_total_cny + positions_value_cny
        total_return = (
            (total_value - account.initial_cash_cny) / account.initial_cash_cny * 100.0
            if account.initial_cash_cny
            else 0.0
        )
        return VirtualTraderAccountResponse(
            account_id=account.id,
            name=account.name,
            status=account.status,
            initial_cash_cny=account.initial_cash_cny,
            cash_cny=round(account.cash_cny, 2),
            cash_hkd=round(account.cash_hkd, 2),
            cash_usd=round(account.cash_usd, 2),
            cash_total_cny=round(cash_total_cny, 2),
            positions=positions,
            positions_value_cny=round(positions_value_cny, 2),
            total_value_cny=round(total_value, 2),
            total_return_pct=round(total_return, 2),
            created_at=_iso(account.created_at),
        )
    except Exception as exc:
        raise _internal_error("Read virtual trader account failed", exc)


@router.get(
    "/trades",
    response_model=VirtualTraderTradeListResponse,
    responses={**AUTH_RESPONSE, 500: {"model": ErrorResponse}},
    summary="查询虚拟交易流水",
)
def list_trades(
    market: Optional[str] = Query(None),
    side: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> VirtualTraderTradeListResponse:
    runner = _build_runner()
    try:
        account = runner.repo.get_account()
        if account is None:
            return VirtualTraderTradeListResponse(items=[], total=0, page=page, page_size=page_size)
        rows, total = runner.repo.list_trades(
            account.id, market=market, side=side, page=page, page_size=page_size
        )
        return VirtualTraderTradeListResponse(
            items=[
                VirtualTraderTradeItem(
                    id=t.id,
                    stock_code=t.stock_code,
                    market=t.market,
                    side=t.side,
                    quantity=t.quantity,
                    price=round(t.price, 4),
                    fee=t.fee,
                    currency=t.currency,
                    reason=t.reason,
                    trade_date=t.trade_date.isoformat(),
                    traded_at=_iso(t.traded_at),
                )
                for t in rows
            ],
            total=total,
            page=page,
            page_size=page_size,
        )
    except Exception as exc:
        raise _internal_error("List virtual trades failed", exc)


@router.get(
    "/predictions",
    response_model=VirtualTraderPredictionListResponse,
    responses={**AUTH_RESPONSE, 500: {"model": ErrorResponse}},
    summary="查询预测记录与复盘结果",
)
def list_predictions(
    status: Optional[str] = Query(None),
    outcome: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> VirtualTraderPredictionListResponse:
    runner = _build_runner()
    try:
        account = runner.repo.get_account()
        if account is None:
            return VirtualTraderPredictionListResponse(
                items=[], total=0, page=page, page_size=page_size
            )
        rows, total = runner.repo.list_predictions(
            account.id, status=status, outcome=outcome, page=page, page_size=page_size
        )
        return VirtualTraderPredictionListResponse(
            items=[
                VirtualTraderPredictionItem(
                    id=p.id,
                    stock_code=p.stock_code,
                    market=p.market,
                    direction=p.direction,
                    anchor_date=p.anchor_date.isoformat(),
                    horizon_days=p.horizon_days,
                    target_price=round(p.target_price, 4),
                    entry_price=round(p.entry_price, 4),
                    rationale=p.rationale,
                    status=p.status,
                    outcome=p.outcome,
                    actual_return_pct=p.actual_return_pct,
                    window_high=p.window_high,
                    window_low=p.window_low,
                )
                for p in rows
            ],
            total=total,
            page=page,
            page_size=page_size,
        )
    except Exception as exc:
        raise _internal_error("List virtual predictions failed", exc)


@router.get(
    "/equity-curve",
    response_model=VirtualTraderEquityCurveResponse,
    responses={**AUTH_RESPONSE, 500: {"model": ErrorResponse}},
    summary="查询每日净值曲线",
)
def get_equity_curve(limit: int = Query(365, ge=1, le=1000)) -> VirtualTraderEquityCurveResponse:
    runner = _build_runner()
    try:
        account = runner.repo.get_account()
        if account is None:
            return VirtualTraderEquityCurveResponse(
                points=[], initial_cash_cny=runner.service.initial_cash_cny
            )
        snapshots = runner.repo.list_snapshots(account.id, limit=limit)
        return VirtualTraderEquityCurveResponse(
            points=[
                VirtualTraderEquityPoint(
                    trade_date=s.trade_date.isoformat(),
                    total_value_cny=s.total_value_cny,
                    daily_return_pct=s.daily_return_pct,
                    positions_count=s.positions_count or 0,
                )
                for s in snapshots
            ],
            initial_cash_cny=account.initial_cash_cny,
        )
    except Exception as exc:
        raise _internal_error("Read equity curve failed", exc)


@router.get(
    "/stats",
    response_model=VirtualTraderStatsResponse,
    responses={**AUTH_RESPONSE, 500: {"model": ErrorResponse}},
    summary="查询预测命中率与绩效统计",
)
def get_stats() -> VirtualTraderStatsResponse:
    runner = _build_runner()
    try:
        account = runner.repo.get_account()
        if account is None:
            return VirtualTraderStatsResponse(
                prediction={"pending": 0, "hit": 0, "miss": 0, "unable": 0, "total": 0},
                total_trades=0,
                sell_trades=0,
                buy_trades=0,
            )
        repo = runner.repo
        prediction = repo.prediction_stats(account.id)
        trades, total = repo.list_trades(account.id, page_size=100)
        while total > len(trades):
            more, _more_total = repo.list_trades(
                account.id, page=len(trades) // 100 + 1, page_size=100
            )
            trades.extend(more)
        all_positions = repo.list_positions(account.id, include_closed=True)
        realized_total = sum(p.realized_pnl or 0.0 for p in all_positions)
        closed_count = sum(1 for p in all_positions if p.status == "closed")
        win_count = sum(1 for p in all_positions if p.status == "closed" and (p.realized_pnl or 0.0) > 0)
        win_rate = round(win_count / closed_count * 100.0, 2) if closed_count else None
        return VirtualTraderStatsResponse(
            prediction=prediction,
            total_trades=total,
            buy_trades=sum(1 for t in trades if t.side == "buy"),
            sell_trades=sum(1 for t in trades if t.side == "sell"),
            win_rate_pct=win_rate,
            realized_pnl_total=round(realized_total, 2),
        )
    except Exception as exc:
        raise _internal_error("Read virtual trader stats failed", exc)


@router.post(
    "/run",
    response_model=VirtualTraderRunResponse,
    responses={**AUTH_RESPONSE, 400: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
    summary="手动触发一轮虚拟交易（各市场幂等，已执行会跳过）",
)
def run_now(request: VirtualTraderRunRequest) -> VirtualTraderRunResponse:
    runner = _build_runner()
    try:
        if request.market:
            results = [runner.run_market(request.market, force=request.force)]
        else:
            results = runner.run_all_markets(force=request.force)
        return VirtualTraderRunResponse(results=results)
    except ValueError as exc:
        raise _bad_request(exc)
    except Exception as exc:
        raise _internal_error("Run virtual trader failed", exc)


@router.post(
    "/reset",
    response_model=VirtualTraderResetResponse,
    responses={**AUTH_RESPONSE, 400: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
    summary="重置虚拟账户（清空全部数据并重新初始建仓）",
)
def reset_account(request: VirtualTraderResetRequest) -> VirtualTraderResetResponse:
    if not request.confirm:
        raise _bad_request(ValueError("必须显式传 confirm=true 才能重置"))
    runner = _build_runner()
    try:
        account = runner.service.reset_account()
        return VirtualTraderResetResponse(success=True, account_id=account.id)
    except Exception as exc:
        raise _internal_error("Reset virtual trader account failed", exc)
