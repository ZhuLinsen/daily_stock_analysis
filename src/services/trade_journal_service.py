# -*- coding: utf-8 -*-
"""Trade journal service: record, discipline-check, and review personal trades."""

from __future__ import annotations

import json
import logging
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

from src.repositories.decision_signal_repo import DecisionSignalRepository
from src.repositories.trade_journal_repo import TradeJournalRepository
from src.services.portfolio_service import VALID_MARKETS
from src.storage import DatabaseManager, TradeJournalEntry

logger = logging.getLogger(__name__)

VALID_SIDES = frozenset({"buy", "sell"})
VALID_EMOTIONS = frozenset({"excited", "calm", "fearful", "fomo", "neutral", "regretful"})
# 方便用户用自然语义记账的别名
_SIDE_ALIASES = {"add": "buy", "加仓": "buy", "买入": "buy", "reduce": "sell", "减仓": "sell", "卖出": "sell"}

BULLISH_SIGNAL_ACTIONS = frozenset({"buy", "add"})
DEFENSIVE_SIGNAL_ACTIONS = frozenset({"reduce", "sell", "avoid"})


class TradeJournalValidationError(ValueError):
    """Raised when a trade journal entry fails validation."""


class TradeJournalNotFoundError(ValueError):
    """Raised when a requested trade journal entry does not exist."""


def normalize_side(value: str) -> str:
    raw = str(value or "").strip()
    key = raw.lower()
    if key in VALID_SIDES:
        return key
    if key in _SIDE_ALIASES:
        return _SIDE_ALIASES[key]
    raise TradeJournalValidationError(f"side must be one of buy/sell: {value}")


def normalize_emotion(value: Optional[str]) -> Optional[str]:
    if value is None or str(value).strip() == "":
        return None
    key = str(value).strip().lower()
    if key not in VALID_EMOTIONS:
        raise TradeJournalValidationError(f"emotion must be one of {sorted(VALID_EMOTIONS)}: {value}")
    return key


def classify_discipline(side: str, signal_action: Optional[str]) -> str:
    """Classify an entry's side against a linked signal's recommended action.

    Returns one of: aligned / contradicted / neutral / no_signal.
    """
    if signal_action is None:
        return "no_signal"
    if side == "buy" and signal_action in BULLISH_SIGNAL_ACTIONS:
        return "aligned"
    if side == "sell" and signal_action in DEFENSIVE_SIGNAL_ACTIONS:
        return "aligned"
    if side == "buy" and signal_action in DEFENSIVE_SIGNAL_ACTIONS:
        return "contradicted"
    if side == "sell" and signal_action in BULLISH_SIGNAL_ACTIONS:
        return "contradicted"
    return "neutral"


def _entry_to_dict(row: TradeJournalEntry) -> Dict[str, Any]:
    return {
        "id": row.id,
        "code": row.code,
        "name": row.name,
        "market": row.market,
        "side": row.side,
        "quantity": row.quantity,
        "price": row.price,
        "fee": row.fee,
        "tax": row.tax,
        "currency": row.currency,
        "trade_date": row.trade_date.isoformat() if row.trade_date else None,
        "thesis": row.thesis,
        "strategy": row.strategy,
        "emotion": row.emotion,
        "plan_followed": row.plan_followed,
        "linked_signal_id": row.linked_signal_id,
        "tags": _parse_tags(row.tags),
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _parse_tags(raw: Optional[str]) -> List[str]:
    if not raw:
        return []
    try:
        value = json.loads(raw)
        if isinstance(value, list):
            return [str(item) for item in value if str(item).strip()]
    except (TypeError, json.JSONDecodeError):
        return []
    return []


class TradeJournalService:
    """Business logic for the personal trade journal."""

    def __init__(
        self,
        repo: Optional[TradeJournalRepository] = None,
        signal_repo: Optional[DecisionSignalRepository] = None,
        db_manager: Optional[DatabaseManager] = None,
    ):
        self.repo = repo or TradeJournalRepository(db_manager)
        self.signal_repo = signal_repo or DecisionSignalRepository(db_manager)
        self.db = db_manager or getattr(self.repo, "db", None) or DatabaseManager.get_instance()

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------
    def create_entry(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        fields = self._validate_payload(payload)
        row = self.repo.create(fields)
        return _entry_to_dict(row)

    def update_entry(self, entry_id: int, payload: Dict[str, Any]) -> Dict[str, Any]:
        fields = self._validate_payload(payload, partial=True)
        row = self.repo.update(entry_id, fields)
        if row is None:
            raise TradeJournalNotFoundError(f"trade journal entry {entry_id} not found")
        return _entry_to_dict(row)

    def delete_entry(self, entry_id: int) -> bool:
        if not self.repo.delete(entry_id):
            raise TradeJournalNotFoundError(f"trade journal entry {entry_id} not found")
        return True

    def get_entry(self, entry_id: int) -> Dict[str, Any]:
        row = self.repo.get(entry_id)
        if row is None:
            raise TradeJournalNotFoundError(f"trade journal entry {entry_id} not found")
        return _entry_to_dict(row)

    def list_entries(
        self,
        *,
        market: Optional[str] = None,
        code: Optional[str] = None,
        side: Optional[str] = None,
        strategy: Optional[str] = None,
        emotion: Optional[str] = None,
        trade_date_from: Optional[str] = None,
        trade_date_to: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Tuple[List[Dict[str, Any]], int]:
        rows, total = self.repo.list(
            market=market,
            code=code,
            side=side,
            strategy=strategy,
            emotion=emotion,
            trade_date_from=_parse_date(trade_date_from),
            trade_date_to=_parse_date(trade_date_to),
            page=page,
            page_size=page_size,
        )
        return [_entry_to_dict(row) for row in rows], total

    # ------------------------------------------------------------------
    # FIFO P&L
    # ------------------------------------------------------------------
    def compute_position_pnl(self, *, market: str, code: str) -> Dict[str, Any]:
        if market not in VALID_MARKETS:
            raise TradeJournalValidationError(f"market must be one of {sorted(VALID_MARKETS)}: {market}")
        rows = self.repo.list_by_code_market(market=market, code=code)

        lots: List[List[float]] = []  # [remaining_qty, cost_basis_per_share]
        realized: List[Dict[str, Any]] = []

        for row in rows:
            if row.side == "buy":
                cost_per_share = row.price + (row.fee + row.tax) / row.quantity
                lots.append([row.quantity, cost_per_share])
            else:
                net_per_share = row.price - (row.fee + row.tax) / row.quantity
                remaining = row.quantity
                while remaining > 1e-9 and lots:
                    lot = lots[0]
                    matched = min(remaining, lot[0])
                    pnl = (net_per_share - lot[1]) * matched
                    realized.append({
                        "buy_price": round(lot[1], 4),
                        "sell_price": round(row.price, 4),
                        "quantity": round(matched, 4),
                        "pnl": round(pnl, 2),
                        "pnl_pct": round(pnl / (lot[1] * matched) * 100, 2) if (lot[1] * matched) else 0.0,
                        "entry_date": row.trade_date.isoformat() if row.trade_date else None,
                    })
                    lot[0] -= matched
                    remaining -= matched
                    if lot[0] <= 1e-9:
                        lots.pop(0)

        open_quantity = round(sum(lot[0] for lot in lots), 4)
        total_cost = sum(lot[0] * lot[1] for lot in lots)
        avg_cost = round(total_cost / open_quantity, 4) if open_quantity > 0 else None
        realized_pnl = round(sum(item["pnl"] for item in realized), 2)

        return {
            "market": market,
            "code": code,
            "realized_pnl": realized_pnl,
            "realized_trades": realized,
            "closed_count": len(realized),
            "open_quantity": open_quantity,
            "avg_cost": avg_cost,
        }

    # ------------------------------------------------------------------
    # Discipline
    # ------------------------------------------------------------------
    def classify_entry_discipline(self, entry_id: int) -> Dict[str, Any]:
        row = self.repo.get(entry_id)
        if row is None:
            raise TradeJournalNotFoundError(f"trade journal entry {entry_id} not found")
        signal_action: Optional[str] = None
        signal_score: Optional[int] = None
        if row.linked_signal_id is not None:
            signal = self.signal_repo.get(row.linked_signal_id)
            if signal is not None:
                signal_action = signal.action
                signal_score = signal.score
        return {
            "entry_id": row.id,
            "side": row.side,
            "linked_signal_id": row.linked_signal_id,
            "signal_action": signal_action,
            "signal_score": signal_score,
            "discipline": classify_discipline(row.side, signal_action),
        }

    # ------------------------------------------------------------------
    # Review
    # ------------------------------------------------------------------
    def review(
        self,
        *,
        market: Optional[str] = None,
        trade_date_from: Optional[str] = None,
        trade_date_to: Optional[str] = None,
    ) -> Dict[str, Any]:
        rows, _ = self.repo.list(
            market=market,
            trade_date_from=_parse_date(trade_date_from),
            trade_date_to=_parse_date(trade_date_to),
            page=1,
            page_size=1000,
        )

        plan_declared = 0
        plan_followed = 0
        linked = 0
        aligned = 0
        emotion_counts: Dict[str, int] = {}
        for row in rows:
            if row.plan_followed is not None:
                plan_declared += 1
                if row.plan_followed:
                    plan_followed += 1
            if row.linked_signal_id is not None:
                linked += 1
                signal = self.signal_repo.get(row.linked_signal_id)
                if signal is not None and classify_discipline(row.side, signal.action) == "aligned":
                    aligned += 1
            if row.emotion:
                emotion_counts[row.emotion] = emotion_counts.get(row.emotion, 0) + 1

        denominator = plan_declared + linked
        discipline_score = None
        if denominator > 0:
            discipline_score = round((plan_followed + aligned) / denominator * 100)

        # Aggregate realized P&L across distinct positions present in the window.
        codes = sorted({(row.market, row.code) for row in rows})
        all_realized: List[Dict[str, Any]] = []
        for mkt, code in codes:
            pnl = self.compute_position_pnl(market=mkt, code=code)
            all_realized.extend(
                {**item, "market": mkt, "code": code} for item in pnl["realized_trades"]
            )

        wins = [t for t in all_realized if t["pnl"] > 0]
        losses = [t for t in all_realized if t["pnl"] < 0]
        total_pnl = round(sum(t["pnl"] for t in all_realized), 2)
        gross_profit = round(sum(t["pnl"] for t in wins), 2)
        gross_loss = round(sum(t["pnl"] for t in losses), 2)

        return {
            "entry_count": len(rows),
            "closed_trade_count": len(all_realized),
            "win_rate": round(len(wins) / len(all_realized) * 100) if all_realized else None,
            "avg_win": round(gross_profit / len(wins), 2) if wins else None,
            "avg_loss": round(gross_loss / len(losses), 2) if losses else None,
            "profit_factor": (
                round(gross_profit / abs(gross_loss), 2) if gross_loss != 0 else None
            ),
            "total_pnl": total_pnl,
            "discipline_score": discipline_score,
            "plan_declared": plan_declared,
            "plan_followed": plan_followed,
            "linked_signal_count": linked,
            "aligned_count": aligned,
            "emotion_breakdown": emotion_counts,
        }

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------
    def _validate_payload(self, payload: Dict[str, Any], *, partial: bool = False) -> Dict[str, Any]:
        fields = dict(payload)
        fields.pop("id", None)
        fields.pop("created_at", None)
        fields.pop("updated_at", None)

        if not partial and "code" not in payload:
            raise TradeJournalValidationError("code is required")
        if "code" in fields and not str(fields["code"]).strip():
            raise TradeJournalValidationError("code must not be empty")

        if "market" in fields:
            market = str(fields["market"]).strip().lower()
            if market not in VALID_MARKETS:
                raise TradeJournalValidationError(
                    f"market must be one of {sorted(VALID_MARKETS)}: {fields['market']}"
                )
            fields["market"] = market

        if "side" in fields:
            fields["side"] = normalize_side(fields["side"])

        if "quantity" in fields and fields["quantity"] is not None:
            quantity = float(fields["quantity"])
            if quantity <= 0:
                raise TradeJournalValidationError("quantity must be positive")
            fields["quantity"] = quantity

        if "price" in fields and fields["price"] is not None:
            price = float(fields["price"])
            if price < 0:
                raise TradeJournalValidationError("price must be non-negative")
            fields["price"] = price

        for key in ("fee", "tax"):
            if key in fields and fields[key] is not None:
                fields[key] = float(fields[key])

        if "emotion" in fields:
            fields["emotion"] = normalize_emotion(fields["emotion"])

        if "plan_followed" in fields and fields["plan_followed"] is not None:
            fields["plan_followed"] = bool(fields["plan_followed"])

        if "trade_date" in fields and isinstance(fields["trade_date"], str):
            fields["trade_date"] = _parse_date(fields["trade_date"])
            if fields["trade_date"] is None:
                raise TradeJournalValidationError("trade_date must be a valid YYYY-MM-DD date")

        if "tags" in fields and fields["tags"] is not None:
            tags = fields["tags"]
            if isinstance(tags, str):
                tags = [t.strip() for t in tags.split(",") if t.strip()]
            if not isinstance(tags, list):
                raise TradeJournalValidationError("tags must be a list of strings")
            fields["tags"] = json.dumps([str(t) for t in tags if str(t).strip()], ensure_ascii=False)

        return fields


def _parse_date(value: Optional[str]) -> Optional[date]:
    if value is None or str(value).strip() == "":
        return None
    text = str(value).strip()
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise TradeJournalValidationError(f"invalid date: {value}") from exc
