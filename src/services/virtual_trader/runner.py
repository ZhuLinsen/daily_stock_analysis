# -*- coding: utf-8 -*-
"""Virtual trader daily runner: per-market idempotent close-price trading loop.

每次 tick 对每个市场：
1. get_effective_trading_date 解析 T（收盘后为当日，收盘前为上一交易日）；
2. runs 表 (T, market) 已存在则跳过（幂等，双进程安全）；
3. 卖出扫描（持仓）→ 买入扫描（universe 备用金）→ 写净值快照 → 评估到期预测。
"""

from __future__ import annotations

import logging
from datetime import date, datetime

import pandas as pd
from typing import Any, Callable, Dict, List, Optional

from src.core.trading_calendar import get_effective_trading_date
from src.repositories.stock_repo import StockRepository
from src.repositories.virtual_trader_repo import VirtualTraderRepository
from src.services.history_loader import load_history_df
from src.services.virtual_trader import strategy
from src.services.virtual_trader.service import (
    DEFAULT_SEED_PORTFOLIO,
    MARKET_CURRENCIES,
    PriceQuote,
    VirtualTraderService,
)

logger = logging.getLogger(__name__)

HISTORY_DAYS = 120


class VirtualTraderRunner:
    """每日虚拟交易执行器。"""

    SUPPORTED_MARKETS = ("cn", "hk", "us")

    def __init__(
        self,
        *,
        service: Optional[VirtualTraderService] = None,
        repo: Optional[VirtualTraderRepository] = None,
        config: Optional[Any] = None,
        history_fn: Optional[Callable[..., Any]] = None,
        trading_date_fn: Optional[Callable[[str], date]] = None,
    ) -> None:
        self.repo = repo or (service.repo if service else VirtualTraderRepository())
        self.service = service or VirtualTraderService(
            repo=self.repo,
            fx_usd_cny=_cfg(config, "virtual_trader_fx_usd_cny", 7.2),
            fx_hkd_cny=_cfg(config, "virtual_trader_fx_hkd_cny", 0.92),
            initial_cash_cny=_cfg(config, "virtual_trader_initial_cash_cny", 1_000_000.0),
            cash_reserve_pct=_cfg(config, "virtual_trader_cash_reserve_pct", 30.0),
            max_position_pct=_cfg(config, "virtual_trader_max_position_pct", 15.0),
            stop_loss_pct=_cfg(config, "virtual_trader_stop_loss_pct", 8.0),
        )
        self.config = config
        self.history_fn = history_fn or load_history_df
        self.trading_date_fn = trading_date_fn or (
            lambda market: get_effective_trading_date(market)
        )
        self._price_cache: Dict[str, Optional[PriceQuote]] = {}
        # seed 建仓价格与日常行情共用同一取价路径
        self.service.get_price_fn = self._get_price_for_market

    # ------------------------------------------------------------------
    def universe_codes(self, account_id: int) -> List[str]:
        """候选池：配置 universe + 自选股 + 内置组合 + 当前持仓。"""
        codes: List[str] = []
        configured = str(_cfg(self.config, "virtual_trader_universe", "") or "").strip()
        if configured:
            codes.extend(p.strip() for p in configured.split(",") if p.strip())
        stock_list = str(_cfg(self.config, "stock_list", "") or "").strip()
        if stock_list:
            codes.extend(p.strip() for p in stock_list.split(",") if p.strip())
        for stocks in DEFAULT_SEED_PORTFOLIO.values():
            codes.extend(item["code"] for item in stocks)
        for position in self.repo.list_open_positions(account_id):
            codes.append(position.stock_code)
        seen = set()
        unique = []
        for code in codes:
            normalized = code.strip()
            if normalized and normalized not in seen:
                seen.add(normalized)
                unique.append(normalized)
        return unique

    def market_of(self, code: str) -> str:
        lowered = code.lower()
        if lowered.startswith("hk") or code.isdigit() and code.startswith(("0", "3", "6")):
            return "hk" if lowered.startswith("hk") else "cn"
        if code.isalpha():
            return "us"
        return "cn"

    # ------------------------------------------------------------------
    def _get_price_for_market(self, code: str) -> Optional[PriceQuote]:
        market = self.market_of(code)
        return self.get_price(code, self.trading_date_fn(market))

    def get_price(self, code: str, target_date: date) -> Optional[PriceQuote]:
        """取 target_date（含）之前最后一根已收盘日线。结果进程内缓存。"""
        cache_key = f"{code}:{target_date.isoformat()}"
        if cache_key in self._price_cache:
            return self._price_cache[cache_key]
        quote: Optional[PriceQuote] = None
        try:
            df, _source = self.history_fn(code, days=HISTORY_DAYS, target_date=target_date)
        except Exception as exc:
            logger.warning("虚拟交易员获取 %s 日线失败: %s", code, exc)
            df = None
        if df is not None and len(df) > 0 and "date" in df and "close" in df:
            bars = _normalize_bar_dates(df, target_date)
            if len(bars) > 0:
                last = bars.iloc[-1]
                close = float(last["close"])
                if close > 0:
                    bar_date = last["date"]
                    quote = PriceQuote(
                        code=code,
                        close=close,
                        trade_date=bar_date if isinstance(bar_date, date) else target_date,
                    )
        self._price_cache[cache_key] = quote
        return quote

    # ------------------------------------------------------------------
    def run_market(self, market: str, *, force: bool = False) -> Dict[str, Any]:
        """对单一市场执行一次每日流程。返回决策摘要。"""
        if market not in self.SUPPORTED_MARKETS:
            return {"status": "skipped", "reason": f"不支持的市场 {market}"}
        trade_date = self.trading_date_fn(market)
        existing = self.repo.get_run(trade_date, market)
        if existing is not None and existing.status in ("success", "running") and not force:
            return {"status": "skipped", "reason": f"{market} {trade_date} 已执行"}

        account = self.repo.get_account()
        if account is None:
            account = self.service.ensure_account()
        run = None
        if existing is None:
            run = self.repo.try_start_run(trade_date, market)
            if run is None:
                return {"status": "skipped", "reason": "并发执行冲突"}
        else:
            run = existing

        try:
            decisions = self._trade_market(account, market, trade_date)
            last_prices = self._collect_last_prices(account)
            snapshot = self.service.write_snapshot(
                account, trade_date=trade_date, last_prices=last_prices
            )
            eval_stats = self._evaluate_predictions(account, trade_date)
            self.repo.finish_run(
                run.id,
                "success",
                decisions={
                    "trades": decisions,
                    "total_value_cny": snapshot.total_value_cny,
                    "prediction_eval": eval_stats,
                },
            )
            return {
                "status": "success",
                "market": market,
                "trade_date": trade_date.isoformat(),
                "trades": decisions,
                "total_value_cny": snapshot.total_value_cny,
                "prediction_eval": eval_stats,
            }
        except Exception as exc:
            logger.exception("虚拟交易员 %s %s 执行失败", market, trade_date)
            self.repo.finish_run(run.id, "failed", error=str(exc))
            return {"status": "failed", "market": market, "error": str(exc)}

    def run_all_markets(self, *, force: bool = False) -> List[Dict[str, Any]]:
        self._price_cache.clear()
        return [self.run_market(market, force=force) for market in self.SUPPORTED_MARKETS]

    # ------------------------------------------------------------------
    def _trade_market(self, account, market: str, trade_date: date) -> List[Dict[str, Any]]:
        decisions: List[Dict[str, Any]] = []
        currency = MARKET_CURRENCIES[market]
        cash_field = {"CNY": "cash_cny", "HKD": "cash_hkd", "USD": "cash_usd"}[currency]

        # 1) 卖出扫描
        for position in self.repo.list_open_positions(account.id, market):
            df, _src = self._history(position.stock_code, trade_date)
            if df is None or len(df) == 0:
                decisions.append({"code": position.stock_code, "action": "skip", "reason": "无日线"})
                continue
            latest_close = float(df["close"].iloc[-1])
            signal = strategy.evaluate_sell(
                df,
                avg_cost=position.avg_cost,
                stop_loss_pct=self.service.stop_loss_pct,
            )
            if signal.action != "sell":
                continue
            self.service.execute_sell(
                account,
                position=position,
                quantity=None,
                price=latest_close,
                trade_date=trade_date,
                reason=signal.reason,
                signal_snapshot=signal.snapshot,
                prediction={
                    "direction": "down",
                    "target_price": signal.target_price or latest_close,
                    "horizon_days": signal.horizon_days,
                    "rationale": signal.reason,
                },
            )
            decisions.append(
                {"code": position.stock_code, "action": "sell", "price": latest_close,
                 "reason": signal.reason}
            )
            # 重新读取账户现金
            account = self.repo.get_account() or account

        # 2) 买入扫描（备用金）
        fresh_account = self.repo.get_account() or account
        for code in self.universe_codes(fresh_account.id):
            market_code = self.market_of(code)
            if market_code != market:
                continue
            position = self.repo.get_open_position(fresh_account.id, code)
            df, _src = self._history(code, trade_date)
            if df is None or len(df) == 0:
                continue
            latest_close = float(df["close"].iloc[-1])
            signal = strategy.evaluate_buy(df)
            if signal.action != "buy":
                continue
            cash = getattr(fresh_account, cash_field) or 0.0
            position_value = position.quantity * latest_close if position else 0.0
            total_asset = self.service.market_total_asset_cny(
                fresh_account,
                [(p, self._position_last_price(p, trade_date))
                 for p in self.repo.list_open_positions(fresh_account.id)],
            ) / self.service.fx_to_cny(currency)
            qty = strategy.estimate_buy_quantity(
                price=latest_close,
                cash=cash,
                position_value=position_value,
                total_asset=total_asset,
                max_position_pct=self.service.max_position_pct,
                reserve_floor_pct=self.service.reserve_floor_pct,
                market=market,
            )
            if qty <= 0:
                decisions.append({"code": code, "action": "skip_buy", "reason": "仓位或备用金约束"})
                continue
            trade = self.service.execute_buy(
                fresh_account,
                code=code,
                name=None,
                market=market,
                quantity=qty,
                price=latest_close,
                trade_date=trade_date,
                reason=signal.reason,
                signal_snapshot=signal.snapshot,
                prediction={
                    "direction": "up",
                    "target_price": signal.target_price or latest_close,
                    "horizon_days": signal.horizon_days,
                    "rationale": signal.reason,
                },
            )
            decisions.append(
                {"code": code, "action": "buy", "quantity": qty, "price": latest_close,
                 "trade_id": trade.id, "reason": signal.reason}
            )
            fresh_account = self.repo.get_account() or fresh_account

        return decisions

    def _history(self, code: str, trade_date: date):
        try:
            return self.history_fn(code, days=HISTORY_DAYS, target_date=trade_date)
        except Exception as exc:
            logger.warning("虚拟交易员获取 %s 日线失败: %s", code, exc)
            return None, "none"

    def _position_last_price(self, position, trade_date: date) -> float:
        quote = self.get_price(position.stock_code, trade_date)
        return quote.close if quote else position.avg_cost

    def _collect_last_prices(self, account) -> Dict[str, float]:
        prices: Dict[str, float] = {}
        for position in self.repo.list_open_positions(account.id):
            quote = self.get_price(position.stock_code, self.trading_date_fn(position.market))
            if quote:
                prices[position.stock_code] = quote.close
        return prices

    def _evaluate_predictions(self, account, trade_date: date) -> Dict[str, int]:
        stock_repo = StockRepository(db_manager=self.repo.db)

        def forward_bars(code: str, anchor: date, horizon: int):
            bars = stock_repo.get_forward_bars(
                code=code, analysis_date=anchor, eval_window_days=horizon
            )
            return [(bar.date, float(bar.close)) for bar in bars]

        return self.service.evaluate_pending_predictions(
            account, matured_before=trade_date, forward_bars_fn=forward_bars
        )


def _cfg(config: Any, key: str, default: Any) -> Any:
    if config is None:
        return default
    return getattr(config, key, default)


def _normalize_bar_dates(df: Any, target_date: date):
    """把 date 列统一为 python date 后按 target_date 过滤。

    load_history_df 返回的 date 列可能是 datetime64 / Timestamp / date 混合形态，
    直接与 date 比较会触发 pandas InvalidComparison。
    """
    try:
        normalized = pd.to_datetime(df["date"]).dt.date
    except Exception:
        return df
    mask = normalized <= target_date
    out = df[mask].copy()
    out["date"] = normalized[mask]
    return out
