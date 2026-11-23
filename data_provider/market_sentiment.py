"""Date-verified Eastmoney limit pools used by close snapshots."""

from dataclasses import dataclass
from datetime import date
import re

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


PROVIDER = "eastmoney"
_BASE_URL = "https://push2ex.eastmoney.com"
_POOLS = {
    "closed": ("getTopicZTPool", "fbt:asc", "lbc", 10000),
    "broken": ("getTopicZBPool", "fbt:asc", None, 5000),
    "previous": ("getYesterdayZTPool", "zs:desc", "ylbc", 5000),
    "down": ("getTopicDTPool", "fund:asc", None, 10000),
}


class LimitPoolUnavailable(ValueError):
    """The requested pool could not be verified."""


@dataclass(frozen=True)
class LimitPool:
    boards: dict[str, int | None]
    response_date: date


def fetch_limit_pool(kind: str, trade_date: date, *, corroborate_for: date | None = None) -> LimitPool:
    """Read a full pool, with an optional historical response used for corroboration only."""
    endpoint, order, board_field, capacity = _POOLS[kind]
    day = trade_date.strftime("%Y%m%d")
    params = {
        "date": day, "Pageindex": 0, "pagesize": capacity, "sort": order,
        "dpt": "wz.ztzt", "ut": "7eea3edcaed734bea9cbfc24409ed989",
    }
    try:
        with requests.Session() as session:
            session.mount(_BASE_URL, HTTPAdapter(max_retries=Retry(
                total=1, backoff_factor=0.5, status_forcelist=(500, 502, 503, 504),
            )))
            response = session.get(f"{_BASE_URL}/{endpoint}", params=params, timeout=(4, 8))
            response.raise_for_status()
            payload = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise LimitPoolUnavailable(f"{kind} pool request failed") from exc
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict) or payload.get("rc") != 0:
        raise LimitPoolUnavailable(f"{kind} pool date or status could not be verified")
    rows, total = data.get("pool"), data.get("tc")
    if not isinstance(rows, list) or type(total) is not int or total != len(rows) or total >= capacity:
        raise LimitPoolUnavailable(f"{kind} pool row count could not be verified")
    reported_date = str(data.get("qdate"))
    if reported_date == day:
        response_date = trade_date
    elif (kind == "closed" and corroborate_for is not None and corroborate_for > trade_date
          and reported_date == corroborate_for.strftime("%Y%m%d") and rows):
        # The historical endpoint can echo the latest query date in qdate.
        # A nonempty response is usable only alongside the independently dated yesterday pool.
        response_date = corroborate_for
    else:
        raise LimitPoolUnavailable(f"{kind} pool date could not be verified")
    pool = {}
    for row in rows:
        code = row.get("c") if isinstance(row, dict) else None
        if not isinstance(code, str) or re.fullmatch(r"[0-9]{6}", code) is None or code in pool:
            raise LimitPoolUnavailable(f"{kind} pool contains invalid or duplicate codes")
        board = row.get(board_field) if board_field else None
        if board_field and (type(board) is not int or board < 1):
            raise LimitPoolUnavailable(f"{kind} pool contains an invalid streak")
        pool[code] = board
    return LimitPool(pool, response_date)
