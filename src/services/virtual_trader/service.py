# -*- coding: utf-8 -*-
"""Virtual trader account service: seed, execute trades, snapshots, prediction evaluation."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import date
from typing import Any, Callable, Dict, List, Optional, Tuple

from src.repositories.virtual_trader_repo import VirtualTraderRepository
from src.services.virtual_trader.strategy import (
    DEFAULT_HORIZON_DAYS,
    compute_fee,
    estimate_buy_quantity,
)

logger = logging.getLogger(__name__)

VIRTUAL_TRADER_ENGINE_VERSION = "virtual-trader-meanrev-v1"

# 市场元数据：币种与汇率配置键
MARKET_CURRENCIES: Dict[str, str] = {
    "cn": "CNY",
    "hk": "HKD",
    "us": "USD",
}

# 内置初始持仓池（seed 与默认候选 universe 共用）
DEFAULT_SEED_PORTFOLIO: Dict[str, List[Dict[str, str]]] = {
    "cn": [
        {"code": "600519", "name": "贵州茅台"},
        {"code": "300750", "name": "宁德时代"},
    ],
    "hk": [
        {"code": "hk00700", "name": "腾讯控股"},
        {"code": "hk09988", "name": "阿里巴巴"},
    ],
    "us": [
        {"code": "AAPL", "name": "苹果"},
        {"code": "NVDA", "name": "英伟达"},
    ],
}

# 市场初始资金分配比例（相对初始总资金）
MARKET_ALLOCATION_PCT: Dict[str, float] = {
    "cn": 40.0,
    "hk": 30.0,
    "us": 30.0,
}


class VirtualTraderError(Exception):
    """Virtual trader domain error."""


@dataclass
class PriceQuote:
    code: str
    close: float
    trade_date: date
    name: Optional[str] = None


class VirtualTraderService:
    """账户操作与交易执行。价格由调用方注入（get_price_fn），保持可测性。"""

    def __init__(
        self,
        *,
        repo: Optional[VirtualTraderRepository] = None,
        get_price_fn: Optional[Callable[[str], Optional[PriceQuote]]] = None,
        fx_usd_cny: float = 7.2,
        fx_hkd_cny: float = 0.92,
        initial_cash_cny: float = 1_000_000.0,
        cash_reserve_pct: float = 30.0,
        max_position_pct: float = 15.0,
        reserve_floor_pct: float = 10.0,
        stop_loss_pct: float = 8.0,
    ) -> None:
        self.repo = repo or VirtualTraderRepository()
        self.get_price_fn = get_price_fn
        self.fx_usd_cny = fx_usd_cny
        self.fx_hkd_cny = fx_hkd_cny
        self.initial_cash_cny = initial_cash_cny
        self.cash_reserve_pct = cash_reserve_pct
        self.max_position_pct = max_position_pct
        self.reserve_floor_pct = reserve_floor_pct
        self.stop_loss_pct = stop_loss_pct

    # ------------------------------------------------------------------
    # 汇率与估值
    # ------------------------------------------------------------------
    def fx_to_cny(self, currency: str) -> float:
        if currency == "CNY":
            return 1.0
        if currency == "HKD":
            return self.fx_hkd_cny
        if currency == "USD":
            return self.fx_usd_cny
        return 1.0

    def market_total_asset_cny(self, account, positions: List[Tuple[Any, float]]) -> float:
        """positions: [(position, last_price)]；按市场币种折 CNY 汇总现金+持仓。"""
        cash_cny = (
            account.cash_cny
            + account.cash_hkd * self.fx_hkd_cny
            + account.cash_usd * self.fx_usd_cny
        )
        value = cash_cny
        for position, last_price in positions:
            value += position.quantity * last_price * self.fx_to_cny(position.currency)
        return value

    # ------------------------------------------------------------------
    # 账户与 seed
    # ------------------------------------------------------------------
    def ensure_account(self, *, auto_seed: bool = True) -> Any:
        account = self.repo.get_account()
        if account is not None:
            return account
        return self.seed_account()

    def seed_account(self) -> Any:
        """按市场分配比例建立初始持仓（70% 建仓 + 各市场留 30% 备用金）。"""
        if self.get_price_fn is None:
            raise VirtualTraderError("get_price_fn 未配置，无法获取建仓价格")

        existing = self.repo.get_account()
        if existing is not None:
            raise VirtualTraderError("账户已存在，请先重置（reset）再 seed")

        account = self.repo.create_account(
            {
                "name": "default",
                "initial_cash_cny": self.initial_cash_cny,
                "cash_cny": 0.0,
                "cash_hkd": 0.0,
                "cash_usd": 0.0,
            }
        )
        decisions: List[Dict[str, Any]] = []
        for market, currency in MARKET_CURRENCIES.items():
            market_cny = self.initial_cash_cny * MARKET_ALLOCATION_PCT[market] / 100.0
            invest_cny = market_cny * (1.0 - self.cash_reserve_pct / 100.0)
            # 市场全额资金先入账（买入时自动扣减），买剩的就是该市场备用金
            self._add_market_cash(account, market, market_cny)

            stocks = DEFAULT_SEED_PORTFOLIO.get(market, [])
            if not stocks:
                continue
            per_stock_cny = invest_cny / len(stocks)
            remaining_cny = invest_cny
            for item in stocks:
                quote = self.get_price_fn(item["code"])
                if quote is None or quote.close <= 0:
                    decisions.append(
                        {"code": item["code"], "market": market, "action": "seed_skip",
                         "reason": "无法获取价格"}
                    )
                    continue
                fx = self.fx_to_cny(currency)
                price_local = quote.close
                budget_cny = min(per_stock_cny, remaining_cny)
                qty = _seed_quantity(price_local, budget_cny / fx, market)
                if qty <= 0:
                    # 高价股一手可能超出等权预算：只要一手仍在市场建仓额度内就兜底买入
                    one_lot = 100 if market in ("cn", "hk") else 1
                    if one_lot * price_local * fx <= remaining_cny:
                        qty = float(one_lot)
                if qty <= 0:
                    decisions.append(
                        {"code": item["code"], "market": market, "action": "seed_skip",
                         "reason": "预算不足一手"}
                    )
                    continue
                trade = self.execute_buy(
                    account,
                    code=item["code"],
                    name=item["name"],
                    market=market,
                    quantity=qty,
                    price=price_local,
                    trade_date=quote.trade_date,
                    reason="初始建仓（等权配置）",
                    signal_snapshot={"seed": True},
                )
                remaining_cny -= qty * price_local * fx
                decisions.append(
                    {"code": item["code"], "market": market, "action": "seed_buy",
                     "quantity": qty, "price": price_local, "trade_id": trade.id}
                )
        account = self.repo.update_account(
            account.id, {"status": "active"}
        ) or account
        logger.info("虚拟交易员账户初始化完成，决策 %d 条", len(decisions))
        return account

    def reset_account(self) -> Any:
        """清空全部虚拟交易数据并重新 seed。"""
        self.repo.delete_all()
        return self.seed_account()

    def _add_market_cash(self, account, market: str, amount_cny: float) -> None:
        currency = MARKET_CURRENCIES[market]
        fx = self.fx_to_cny(currency)
        amount_local = amount_cny / fx
        field = {"CNY": "cash_cny", "HKD": "cash_hkd", "USD": "cash_usd"}[currency]
        current = getattr(account, field) or 0.0
        setattr(account, field, current + amount_local)
        self.repo.update_account(account.id, {field: getattr(account, field)})

    # ------------------------------------------------------------------
    # 交易执行
    # ------------------------------------------------------------------
    def execute_buy(
        self,
        account,
        *,
        code: str,
        name: Optional[str],
        market: str,
        quantity: float,
        price: float,
        trade_date: date,
        reason: str,
        signal_snapshot: Optional[Dict[str, Any]] = None,
        prediction: Optional[Dict[str, Any]] = None,
    ):
        """执行虚拟买入：扣现金、建/加仓位、写流水与预测。"""
        currency = MARKET_CURRENCIES[market]
        fee = compute_fee(side="buy", price=price, quantity=quantity, market=market)
        cost = quantity * price + fee
        cash_field = {"CNY": "cash_cny", "HKD": "cash_hkd", "USD": "cash_usd"}[currency]
        cash = getattr(account, cash_field) or 0.0
        if cash < cost:
            raise VirtualTraderError(
                f"{code} 现金不足：需要 {cost:.2f} {currency}，可用 {cash:.2f}"
            )
        setattr(account, cash_field, cash - cost)
        account = self.repo.update_account(account.id, {cash_field: getattr(account, cash_field)})

        position = self.repo.get_open_position(account.id, code)
        if position is None:
            position = self.repo.create_position(
                {
                    "account_id": account.id,
                    "stock_code": code,
                    "name": name,
                    "market": market,
                    "currency": currency,
                    "quantity": quantity,
                    "avg_cost": price,
                    "status": "open",
                    "opened_at": trade_date,
                }
            )
        else:
            total_qty = position.quantity + quantity
            new_avg = (position.avg_cost * position.quantity + price * quantity) / total_qty
            position = self.repo.update_position(
                position.id,
                {"quantity": total_qty, "avg_cost": round(new_avg, 6)},
            )

        trade = self.repo.create_trade(
            {
                "account_id": account.id,
                "position_id": position.id,
                "stock_code": code,
                "market": market,
                "side": "buy",
                "quantity": quantity,
                "price": price,
                "fee": fee,
                "currency": currency,
                "reason": reason,
                "signal_snapshot_json": _dumps(signal_snapshot),
                "trade_date": trade_date,
            }
        )
        if prediction:
            self.repo.create_prediction(
                {
                    "account_id": account.id,
                    "trade_id": trade.id,
                    "stock_code": code,
                    "market": market,
                    "direction": prediction.get("direction", "up"),
                    "anchor_date": trade_date,
                    "horizon_days": prediction.get("horizon_days", DEFAULT_HORIZON_DAYS),
                    "target_price": prediction["target_price"],
                    "entry_price": price,
                    "rationale": prediction.get("rationale", reason),
                }
            )
        return trade

    def execute_sell(
        self,
        account,
        *,
        position,
        quantity: Optional[float],
        price: float,
        trade_date: date,
        reason: str,
        signal_snapshot: Optional[Dict[str, Any]] = None,
        prediction: Optional[Dict[str, Any]] = None,
    ):
        """执行虚拟卖出：加现金、减仓位、写流水与预测。quantity=None 全部卖出。"""
        market = position.market
        currency = MARKET_CURRENCIES[market]
        sell_qty = position.quantity if quantity is None else min(quantity, position.quantity)
        if sell_qty <= 0:
            raise VirtualTraderError(f"{position.stock_code} 卖出数量无效")
        fee = compute_fee(side="sell", price=price, quantity=sell_qty, market=market)
        proceeds = sell_qty * price - fee
        cash_field = {"CNY": "cash_cny", "HKD": "cash_hkd", "USD": "cash_usd"}[currency]
        setattr(
            account,
            cash_field,
            (getattr(account, cash_field) or 0.0) + proceeds,
        )
        account = self.repo.update_account(account.id, {cash_field: getattr(account, cash_field)})

        realized = (price - position.avg_cost) * sell_qty - fee
        remaining = position.quantity - sell_qty
        if remaining > 0:
            position = self.repo.update_position(
                position.id,
                {
                    "quantity": remaining,
                    "realized_pnl": (position.realized_pnl or 0.0) + realized,
                },
            )
        else:
            position = self.repo.update_position(
                position.id,
                {
                    "quantity": 0.0,
                    "status": "closed",
                    "realized_pnl": (position.realized_pnl or 0.0) + realized,
                    "closed_at": trade_date,
                },
            )

        trade = self.repo.create_trade(
            {
                "account_id": account.id,
                "position_id": position.id,
                "stock_code": position.stock_code,
                "market": market,
                "side": "sell",
                "quantity": sell_qty,
                "price": price,
                "fee": fee,
                "currency": currency,
                "reason": reason,
                "signal_snapshot_json": _dumps(signal_snapshot),
                "trade_date": trade_date,
            }
        )
        if prediction:
            self.repo.create_prediction(
                {
                    "account_id": account.id,
                    "trade_id": trade.id,
                    "stock_code": position.stock_code,
                    "market": market,
                    "direction": prediction.get("direction", "down"),
                    "anchor_date": trade_date,
                    "horizon_days": prediction.get("horizon_days", DEFAULT_HORIZON_DAYS),
                    "target_price": prediction["target_price"],
                    "entry_price": price,
                    "rationale": prediction.get("rationale", reason),
                }
            )
        return trade

    # ------------------------------------------------------------------
    # 快照与预测评估
    # ------------------------------------------------------------------
    def write_snapshot(
        self, account, *, trade_date: date, last_prices: Dict[str, float]
    ) -> Any:
        positions = self.repo.list_open_positions(account.id)
        positions_value: Dict[str, Any] = {}
        total_value_cny = (
            account.cash_cny
            + account.cash_hkd * self.fx_hkd_cny
            + account.cash_usd * self.fx_usd_cny
        )
        for p in positions:
            last_price = last_prices.get(p.stock_code)
            if last_price is None:
                last_price = p.avg_cost
            value_local = p.quantity * last_price
            value_cny = value_local * self.fx_to_cny(p.currency)
            total_value_cny += value_cny
            positions_value[p.stock_code] = {
                "market": p.market,
                "quantity": p.quantity,
                "last_price": last_price,
                "value_cny": round(value_cny, 2),
            }
        latest = None
        for snap in reversed(self.repo.list_snapshots(account.id, limit=365)):
            if snap.trade_date < trade_date:
                latest = snap
                break
        daily_return = None
        if latest is not None and latest.total_value_cny:
            daily_return = round(
                (total_value_cny - latest.total_value_cny) / latest.total_value_cny * 100.0, 4
            )
        return self.repo.upsert_snapshot(
            {
                "account_id": account.id,
                "trade_date": trade_date,
                "cash_json": _dumps(
                    {"cny": account.cash_cny, "hkd": account.cash_hkd, "usd": account.cash_usd}
                ),
                "positions_value_json": _dumps(positions_value),
                "total_value_cny": round(total_value_cny, 2),
                "daily_return_pct": daily_return,
                "positions_count": len(positions),
            }
        )

    def evaluate_pending_predictions(
        self,
        account,
        *,
        matured_before: date,
        forward_bars_fn: Callable[[str, date, int], List[Tuple[date, float]]],
    ) -> Dict[str, int]:
        """评估到期预测：direction=up 看窗口内最高价触及目标价；down 看最低价。"""
        pending = self.repo.list_pending_predictions(account.id, matured_before=matured_before)
        stats = {"evaluated": 0, "hit": 0, "miss": 0, "unable": 0}
        for pred in pending:
            bars = forward_bars_fn(pred.stock_code, pred.anchor_date, pred.horizon_days)
            if not bars:
                self.repo.update_prediction(
                    pred.id,
                    {
                        "status": "unable",
                        "outcome": "unable",
                        "rationale": (pred.rationale or "") + " | 复盘：无可用日线",
                        "evaluated_at": __import__("datetime").datetime.utcnow(),
                    },
                )
                stats["unable"] += 1
                continue
            closes = [close for _d, close in bars]
            end_close = closes[-1]
            actual_return = (end_close - pred.entry_price) / pred.entry_price * 100.0
            if pred.direction == "up":
                hit = max(closes) >= pred.target_price
            else:
                hit = min(closes) <= pred.target_price
            self.repo.update_prediction(
                pred.id,
                {
                    "status": "evaluated",
                    "outcome": "hit" if hit else "miss",
                    "actual_return_pct": round(actual_return, 4),
                    "window_high": round(max(closes), 4),
                    "window_low": round(min(closes), 4),
                    "evaluated_at": __import__("datetime").datetime.utcnow(),
                },
            )
            stats["evaluated"] += 1
            stats["hit" if hit else "miss"] += 1
        return stats


def _seed_quantity(price: float, budget: float, market: str) -> float:
    """按预算取整手数量（cn/hk 100 股一手，us 整股）。"""
    if price <= 0 or budget <= 0:
        return 0.0
    raw = budget / price
    if market in ("cn", "hk"):
        return float(int(raw // 100) * 100)
    return float(int(raw))


def _dumps(value: Optional[Dict[str, Any]]) -> Optional[str]:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False, default=str)
