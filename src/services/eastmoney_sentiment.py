"""Source-scoped Eastmoney sentiment snapshots and same-day market breadth."""

from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import math

from src.core.trading_calendar import get_trading_dates
from src.data.csmar_daily import CsmarDataset, CsmarDay, CsmarSourceError
from src.repositories.sentiment_repo import SentimentRepository
from src.services.sentiment_calendar import trading_sessions
from src.services.sentiment_snapshot_service import compute_snapshot, higher_board_promotions, limit_up_ladder


EASTMONEY_MARKET = "CN_A_EASTMONEY_POOL"
EASTMONEY_VERSION = "eastmoney-pool-v2-market-day-streak"
EASTMONEY_DAILY_VERSION = "eastmoney-pool-v3-daily-provider-streak"
MARKET_TZ = timezone(timedelta(hours=8))


def _fetch_frame(function, kind: str, day: date, *, timeout: int = 15,
                 attempts: int = 2, allow_empty: bool = False, **kwargs):
    from data_provider.akshare_fetcher import _akshare_call_with_timeout

    last_error = None
    for _ in range(attempts):
        try:
            result = _akshare_call_with_timeout(function, timeout=timeout, call_name="sentiment_" + kind, **kwargs)
            if result is not None and (not result.empty or allow_empty):
                return result
        except Exception as exc:
            last_error = exc
    raise CsmarSourceError(f"Eastmoney {kind} pool empty or unavailable for {day}") from last_error


def _fetch_pool(kind: str, day: date):
    import akshare as ak

    names = {
        "closed": "stock_zt_pool_em", "broken": "stock_zt_pool_zbgc_em",
        "previous": "stock_zt_pool_previous_em", "down": "stock_zt_pool_dtgc_em",
    }
    function = getattr(ak, names[kind], None)
    if function is None:
        raise CsmarSourceError(f"Eastmoney {kind} endpoint unavailable for {day}")
    return _fetch_frame(function, kind, day, date=day.strftime("%Y%m%d"), allow_empty=kind == "down")


def _fetch_spot(day: date):
    import akshare as ak

    function = getattr(ak, "stock_zh_a_spot_em", None)
    if function is None:
        raise CsmarSourceError(f"Eastmoney spot endpoint unavailable for {day}")
    # AkShare fetches the market in pages. Bound the entire request, including paging.
    return _fetch_frame(function, "spot", day, timeout=120, attempts=1)


def _codes(frame, kind: str, day: date) -> set[str]:
    if "代码" not in frame.columns:
        raise CsmarSourceError(f"Eastmoney {kind} pool for {day} lacks stock codes")
    codes = [str(value).strip() for value in frame["代码"]]
    if any(len(code) != 6 or not code.isascii() or not code.isdigit() for code in codes):
        raise CsmarSourceError(f"Eastmoney {kind} pool for {day} contains invalid stock codes")
    if len(codes) != len(set(codes)):
        raise CsmarSourceError(f"Eastmoney {kind} pool for {day} contains duplicate stock codes")
    cap = {"closed": 10000, "broken": 5000, "previous": 5000, "down": 10000}.get(kind)
    if cap is not None and len(codes) >= cap:
        raise CsmarSourceError(f"Eastmoney {kind} pool for {day} may be truncated")
    return set(codes)


def _fetch_down_codes(day: date) -> set[str]:
    frame = _fetch_pool("down", day)
    if not frame.empty:
        return _codes(frame, "down", day)

    # AkShare drops the date and total from an empty response. Verify the zero
    # against the same public endpoint before treating it as a market observation.
    import requests

    day_key = day.strftime("%Y%m%d")
    params = {
        "date": day_key, "Pageindex": 0, "pagesize": 1, "sort": "fund:asc",
        "dpt": "wz.ztzt", "ut": "7eea3edcaed734bea9cbfc24409ed989",
    }
    try:
        response = requests.get("https://push2ex.eastmoney.com/getTopicDTPool", params=params, timeout=12)
        response.raise_for_status()
        payload = response.json()
        data = payload.get("data") if isinstance(payload, dict) else None
        if (isinstance(data, dict) and payload.get("rc") == 0
                and str(data.get("qdate")) == day_key and data.get("tc") == 0 and data.get("pool") == []):
            return set()
    except (requests.RequestException, ValueError) as exc:
        raise CsmarSourceError(f"Eastmoney empty down pool could not be confirmed for {day}") from exc
    raise CsmarSourceError(f"Eastmoney empty down pool could not be confirmed for {day}")


def _streaks(frame, field: str, day: date) -> dict[str, int]:
    if field not in frame.columns:
        raise CsmarSourceError(f"Eastmoney pool for {day} lacks {field}")
    counts = {}
    for code, count in zip(frame["代码"], frame[field]):
        try:
            number = float(count)
            if not number.is_integer() or not 1 <= number <= 30:
                raise ValueError
            counts[str(code).strip()] = int(number)
        except (TypeError, ValueError, OverflowError) as exc:
            raise CsmarSourceError(f"Eastmoney pool for {day} has invalid streak counts") from exc
    return counts


def _daily_breadth(day: date, closed_frame, known_traded: set[str]) -> tuple[dict, dict, dict]:
    """Use one valid quote universe as the denominator for both breadth measures."""
    metrics = {"limit_down_coverage": None, "advancing_ratio": None, "turnover_yuan": None}
    components = {"eligible_quote_count": None, "limit_down_count": None, "advancing_count": None}
    quality = {"quote_status": "unavailable", "limit_down_status": "unavailable",
               "turnover_status": "unavailable"}
    try:
        spot = _fetch_spot(day)
        _codes(spot, "spot", day)
        required = ["代码", "最新价", "涨跌幅", "成交量"]
        if not set(required).issubset(spot.columns):
            raise CsmarSourceError("Eastmoney spot lacks breadth fields")
        eligible = {}
        for code, price, change, volume in spot[required].itertuples(index=False, name=None):
            try:
                price, change, volume = float(price), float(change), float(volume)
            except (TypeError, ValueError, OverflowError):
                continue
            if all(math.isfinite(x) for x in (price, change, volume)) and price > 0 and volume > 0:
                eligible[str(code).strip()] = (price, change)
        if not eligible or not known_traded.issubset(eligible):
            raise CsmarSourceError("Eastmoney spot does not cover the known traded pool")
        # Spot has no date argument. Check its prices against the dated close pool.
        if "最新价" not in closed_frame.columns:
            raise CsmarSourceError("Eastmoney close pool lacks prices for quote validation")
        for code, price in zip(closed_frame["代码"], closed_frame["最新价"]):
            try:
                matches = math.isclose(eligible[str(code).strip()][0], float(price), rel_tol=0, abs_tol=0.001)
            except (TypeError, ValueError, OverflowError):
                matches = False
            if not matches:
                raise CsmarSourceError("Eastmoney spot prices disagree with the dated close pool")
        if datetime.now(MARKET_TZ).date() != day:
            raise CsmarSourceError("Eastmoney spot collection crossed the session date")
    except CsmarSourceError:
        return metrics, components, quality

    count = len(eligible)
    advancing = sum(change > 0 for _, change in eligible.values())
    components.update(eligible_quote_count=count, advancing_count=advancing)
    metrics["advancing_ratio"] = advancing / count
    quality["quote_status"] = "available"
    if "成交额" in spot.columns:
        try:
            amounts = [float(amount) for code, amount in zip(spot["代码"], spot["成交额"])
                       if str(code).strip() in eligible]
            if len(amounts) == count and all(math.isfinite(amount) and amount > 0 for amount in amounts):
                metrics["turnover_yuan"] = math.fsum(amounts)
                quality["turnover_status"] = "available"
        except (TypeError, ValueError, OverflowError):
            pass
    try:
        down = _fetch_down_codes(day)
        if not down.issubset(eligible) or any(eligible[code][1] >= 0 for code in down):
            raise CsmarSourceError("Eastmoney down pool disagrees with the traded quote universe")
    except CsmarSourceError:
        return metrics, components, quality
    components["limit_down_count"] = len(down)
    metrics["limit_down_coverage"] = len(down) / count
    quality["limit_down_status"] = "available"
    return metrics, components, quality


def _build_daily_snapshot(trade_date: date, previous_date: date) -> dict:
    current = _fetch_pool("closed", trade_date)
    closed = _codes(current, "closed", trade_date)
    broken = _codes(_fetch_pool("broken", trade_date), "broken", trade_date)
    prior_pool = _fetch_pool("previous", trade_date)
    _codes(prior_pool, "previous", trade_date)
    today_streaks = _streaks(current, "连板数", trade_date)
    prior_streaks = _streaks(prior_pool, "昨日连板数", trade_date)
    if closed & broken:
        raise CsmarSourceError("Eastmoney closed and broken pools overlap")
    if any(length != prior_streaks.get(code, 0) + 1 for code, length in today_streaks.items()):
        raise CsmarSourceError("Eastmoney streak counts disagree with the previous pool")

    first_board = {code for code, length in prior_streaks.items() if length == 1}
    promoted = first_board & closed
    touched = closed | broken
    highest = max(today_streaks.values())
    metrics, components, breadth_quality = _daily_breadth(trade_date, current, touched)
    metrics.update(
        limit_up_count=len(closed), break_rate=len(broken) / len(touched),
        max_consecutive=highest, promotion_1_to_2=len(promoted) / len(first_board) if first_board else None,
        limit_up_ladder=limit_up_ladder(today_streaks),
        higher_board_promotions=higher_board_promotions(prior_streaks, closed),
    )
    components.update(
        limit_up_codes=sorted(closed), broken_codes=sorted(broken), touched_codes=sorted(touched),
        max_consecutive_codes=sorted(code for code, count in today_streaks.items() if count == highest),
        prior_first_board_codes=sorted(first_board), promoted_codes=sorted(promoted),
        break_numerator=len(broken), break_denominator=len(touched),
        promotion_numerator=len(promoted), promotion_denominator=len(first_board),
    )
    inputs = {"today_streaks": today_streaks, "prior_streaks": prior_streaks,
              "components": components, "turnover_yuan": metrics["turnover_yuan"]}
    digest = hashlib.sha256(json.dumps(inputs, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return {
        "market": EASTMONEY_MARKET, "trade_date": trade_date, "previous_trade_date": previous_date,
        "definition_version": EASTMONEY_DAILY_VERSION,
        "quality_status": "complete" if all(value == "available" for value in breadth_quality.values()) else "partial",
        "metrics": metrics, "components": components,
        "provider_trace": {"provider": "eastmoney_akshare", "as_of_sha256": digest,
                           "retrieved_at": datetime.now(timezone.utc).isoformat()},
        "completeness": {
            "scope": "Eastmoney provider limit pools and eligible same-day spot quotes",
            "independent_market_coverage_verified": False,
            "streak_counts_match_previous_pool": True,
            "closed_broken_disjoint": True,
            **breadth_quality,
        },
    }


def build_eastmoney_snapshot(trade_date: date) -> dict:
    now = datetime.now(MARKET_TZ)
    if trade_date > now.date() or (trade_date == now.date() and now.hour < 15):
        raise CsmarSourceError("Eastmoney close snapshot requires a completed trading session")
    sessions = sorted(trading_sessions(get_trading_dates, trade_date - timedelta(days=100), trade_date))
    if not sessions or sessions[-1] != trade_date:
        raise CsmarSourceError("target date is not a supported trading session")
    if trade_date == now.date():
        if len(sessions) < 2:
            raise CsmarSourceError("previous trading session is unavailable")
        return _build_daily_snapshot(trade_date, sessions[-2])

    current = _fetch_pool("closed", trade_date)
    closed = _codes(current, "closed", trade_date)
    # The broken-pool interface has the narrowest history window. Check it
    # before fetching each earlier session to fail old backfills promptly.
    broken = _codes(_fetch_pool("broken", trade_date), "broken", trade_date)
    if closed & broken:
        raise CsmarSourceError("Eastmoney closed and broken pools overlap")
    claimed = _streaks(current, "连板数", trade_date)
    needed = max(3, max(claimed.values()) + 1)
    if len(sessions) < needed:
        raise CsmarSourceError("not enough trading sessions to verify streak history")
    selected = sessions[-needed:]
    days = {trade_date: CsmarDay(closed=closed)}
    for day in selected[:-1]:
        days[day] = CsmarDay(closed=_codes(_fetch_pool("closed", day), "closed", day))
    previous = _codes(_fetch_pool("previous", trade_date), "previous", trade_date)
    if previous != days[selected[-2]].closed:
        raise CsmarSourceError("Eastmoney previous pool differs from previous session's closed pool")
    days[trade_date].broken = broken
    days[trade_date].touched = closed | broken

    for code, expected in claimed.items():
        actual = 0
        for day in reversed(selected):
            if code not in days[day].closed:
                break
            actual += 1
        if actual != expected:
            raise CsmarSourceError("Eastmoney streak counts disagree with daily pools")

    inputs = {"closed": {day.isoformat(): sorted(days[day].closed) for day in selected},
              "broken": sorted(broken), "previous": sorted(previous), "claimed_streak": claimed}
    digest = hashlib.sha256(json.dumps(inputs, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    # Reuse the existing pool calculation. Replace its CSMAR-specific trace and
    # scope below before the result can be persisted or returned.
    dataset = CsmarDataset(days, digest, "", sum(len(x.closed) for x in days.values()), "", "A1:B1", 2)
    snapshot = compute_snapshot(dataset, trade_date)
    snapshot["market"] = EASTMONEY_MARKET
    snapshot["definition_version"] = EASTMONEY_VERSION
    snapshot["provider_trace"] = {"provider": "eastmoney_akshare", "as_of_sha256": digest,
                                  "retrieved_at": datetime.now(timezone.utc).isoformat()}
    snapshot["completeness"] = {
        "scope": "Eastmoney provider limit pools; not verified full A-share or main-board coverage",
        "date_min": selected[0].isoformat(), "date_max": trade_date.isoformat(),
        "date_count": len(selected), "previous_pool_matches": True,
        "streak_counts_match": True, "closed_broken_disjoint": True,
        "independent_market_coverage_verified": False,
    }
    return snapshot


def generate_eastmoney_snapshot(session, trade_date: date):
    return SentimentRepository(session).save(build_eastmoney_snapshot(trade_date))
