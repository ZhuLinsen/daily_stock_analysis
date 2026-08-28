"""Current regular-session status for the markets supported by DSA."""

from datetime import datetime, timezone

from fastapi import APIRouter

from src.core.trading_calendar import build_market_phase_context, get_next_session_open

router = APIRouter()

MARKET_STATUS_REGIONS = ("cn", "hk", "us", "jp", "kr")


@router.get("/status")
async def get_market_status():
    """Return calendar-aware market phases without triggering market data calls."""
    current_time = datetime.now(timezone.utc)
    markets = []

    for market in MARKET_STATUS_REGIONS:
        context = build_market_phase_context(
            market=market,
            current_time=current_time,
            trigger_source="market_status",
        )
        item = context.to_dict()
        next_open = get_next_session_open(market, current_time=current_time)
        item["next_session_open"] = next_open.isoformat() if next_open is not None else None
        markets.append(item)

    return {
        "generated_at": current_time.isoformat(),
        "markets": markets,
    }
