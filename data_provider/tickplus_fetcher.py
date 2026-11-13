"""TickPlus Basic A-share/ETF adapter using the shared manager fallback chain."""
from __future__ import annotations

from copy import deepcopy
import math
import re
from threading import RLock
from time import monotonic

import pandas as pd
import requests

from src.services.stock_list_parser import ParseStatus, parse_analysis_target
from .base import BaseFetcher, DataFetchError, STANDARD_COLUMNS, _is_etf_code
from .realtime_types import RealtimeSource, UnifiedRealtimeQuote, safe_float, safe_int

_ADJUSTMENTS = {"none": "1", "forward": "2", "backward": "3"}


class TickPlusFetcher(BaseFetcher):
    name = "TickPlusFetcher"
    priority = 0

    def __init__(self, api_key: str, priority: int = 0, *, kline_adjust: str = "none"):
        if kline_adjust not in _ADJUSTMENTS:
            raise ValueError("Unsupported TickPlus adjustment mode")
        self.api_key = api_key.strip()
        self.priority = priority
        self.kline_adjust = kline_adjust
        self._names = {}
        self._loaded_name_symbols = set()
        self._lock = RLock()
        self._cooldowns = {}
        self._quote_cache = {}
        self._successful_endpoints = set()

    def _endpoint_ready(self, endpoint):
        with self._lock:
            return bool(self.api_key) and monotonic() >= self._cooldowns.get(endpoint, 0)

    def is_available(self, capability=""):
        if capability == "daily_data":
            return self._endpoint_ready("daykline")
        if capability == "realtime_quote":
            return any(self._endpoint_ready(e) for e in ("fullfactor", "fullquotes"))
        return any(self._endpoint_ready(e) for e in ("daykline", "fullfactor", "fullquotes", "list"))

    @property
    def runtime_status(self):
        # Request eligibility is not proof that a configured key has been validated.
        with self._lock:
            if any(self._endpoint_ready(endpoint) for endpoint in self._successful_endpoints):
                return "ok"
            if not self.is_available():
                return "unavailable"
            return "unknown"

    @staticmethod
    def _symbol(stock_code):
        target = parse_analysis_target(stock_code)
        if target.exchange not in {"SH", "SZ", "BJ"}:
            raise DataFetchError("TickPlus does not support this market")
        # Bare 000001/000016 carry a matching index as metadata, but remain stocks.
        if target.asset_type == ParseStatus.INDEX:
            raise DataFetchError("TickPlus index routing is not enabled")
        code = target.normalized_code
        if not re.fullmatch(r"\d{6}", code):
            raise DataFetchError("TickPlus supports mainland A-shares and ETFs only")
        return code, "etf" if _is_etf_code(code) else "stock"

    def _request(self, endpoint, **params):
        if not self._endpoint_ready(endpoint):
            raise DataFetchError(f"TickPlus {endpoint} is not configured or is cooling down")
        try:
            response = requests.get(
                f"http://api.tickplus.org/plus/basic/{endpoint}",
                params={**params, "token": self.api_key}, timeout=15,
            )
            response.raise_for_status()
            rows = response.json()
            if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
                raise ValueError("unexpected response")
            with self._lock:
                self._successful_endpoints.add(endpoint)
            return rows
        except (requests.RequestException, ValueError):
            with self._lock:
                self._cooldowns[endpoint] = monotonic() + 60
            # Never expose exception URLs or provider bodies: both can contain the token.
            raise DataFetchError(f"TickPlus {endpoint} request failed; retry after cooldown") from None

    def _fetch_raw_data(self, stock_code, start_date, end_date):
        code, symbol = self._symbol(stock_code)
        frame = pd.DataFrame(self._request(
            "daykline", symbol=symbol, code=code, period="1d", dividend=_ADJUSTMENTS[self.kline_adjust],
            startDate=start_date, endDate=end_date,
        ))
        if not frame.empty and "t" in frame:
            dates = pd.to_datetime(frame["t"], errors="coerce", format="mixed")
            frame = frame[(dates >= pd.Timestamp(start_date)) & (dates < pd.Timestamp(end_date) + pd.Timedelta(days=1))]
        return frame

    def _normalize_data(self, df, stock_code):
        if df.empty:
            return pd.DataFrame(columns=["code", *STANDARD_COLUMNS])
        required = {"code", "t", "o", "c", "h", "l", "v", "a", "pc"}
        if not required.issubset(df.columns):
            raise DataFetchError("TickPlus daily response missing required fields")
        code, _ = self._symbol(stock_code)
        if not df["code"].astype(str).eq(code).all():
            raise DataFetchError("TickPlus returned another target")
        result = df.rename(columns={"t": "date", "o": "open", "c": "close",
                                    "h": "high", "l": "low", "v": "volume", "a": "amount"}).copy()
        result["date"] = pd.to_datetime(result["date"], errors="coerce", format="mixed").dt.strftime("%Y-%m-%d")
        for field in ("open", "close", "high", "low", "volume", "amount", "pc"):
            result[field] = pd.to_numeric(result[field], errors="coerce").replace([math.inf, -math.inf], float("nan"))
        result["volume"] *= 100  # Provider lots -> project shares (A-shares and ETFs).
        result["pct_chg"] = (result["close"] / result["pc"].where(result["pc"] > 0) - 1) * 100
        result["code"] = code
        result = result.dropna(subset=["date", "open", "close", "high", "low", "volume"])
        result = result[(result["close"] > 0) & (result["volume"] >= 0)]
        result = result[["code", *STANDARD_COLUMNS]].sort_values("date").drop_duplicates("date").reset_index(drop=True)
        result.attrs["price_adjustment"] = self.kline_adjust
        return result

    @staticmethod
    def _number(value):
        value = safe_float(value)
        return value if value is not None and math.isfinite(value) else None

    def _quote_from_row(self, row, code, symbol, *, factor):
        def number(basic, metric):
            return self._number(row.get(metric if factor else basic))

        price, previous = number("c", "zxj"), number("pc", "zrspj")
        if price is None or price <= 0:
            raise DataFetchError("TickPlus quote missing valid price")
        volume = number("v", "cjl")
        timestamp = pd.to_datetime(row.get("tradeDate" if factor else "t"), errors="coerce")
        provider_timestamp = None
        if pd.notna(timestamp):
            if timestamp.tzinfo is None:
                timestamp = timestamp.tz_localize("Asia/Shanghai")
            provider_timestamp = timestamp.isoformat()
        quote = UnifiedRealtimeQuote(
            code=code, name=row.get("name") or self._names.get(code, ""),
            source=RealtimeSource.TICKPLUS, price=price, pre_close=previous,
            change_amount=price - previous if previous and previous > 0 else None,
            change_pct=(price / previous - 1) * 100 if previous and previous > 0 else None,
            open_price=number("o", "open"), high=number("h", "high"),
            low=number("l", "low"), amount=number("a", "cje"),
            volume=safe_int(volume * 100) if volume is not None and volume >= 0 else None,
            provider_timestamp=provider_timestamp,
        )
        if factor:
            for field, key in {"volume_ratio": "lb", "turnover_rate": "hsl", "amplitude": "zf",
                               "total_mv": "zsz", "circ_mv": "ltsz", "change_60d": "zdf60"}.items():
                setattr(quote, field, self._number(row.get(key)))
            # ETF factor responses contain sentinel 0 PE/PB: these are not fund valuations.
            if symbol == "stock":
                quote.pe_ratio = self._number(row.get("dtsyl"))
                quote.pb_ratio = self._number(row.get("sjl"))
        return quote

    def _load_quotes(self, codes, symbol):
        quotes = {}
        for endpoint in ("fullfactor", "fullquotes"):
            missing = [code for code in codes if code not in quotes]
            if not missing:
                break
            try:
                rows = self._request(endpoint, symbol=symbol, code=",".join(missing))
            except DataFetchError:
                continue  # Indicator failures must not suppress the basic quote endpoint.
            for row in rows:
                code = str(row.get("code", ""))
                if code not in missing:
                    continue
                try:
                    quotes[code] = self._quote_from_row(row, code, symbol, factor=endpoint == "fullfactor")
                except DataFetchError:
                    continue
        now = monotonic()
        with self._lock:
            self._quote_cache.update({code: (now, quote) for code, quote in quotes.items()})
        return quotes

    def get_realtime_quote(self, stock_code):
        code, symbol = self._symbol(stock_code)
        with self._lock:
            cached = self._quote_cache.get(code)
            if cached and monotonic() - cached[0] < 30:
                return deepcopy(cached[1])
        quote = self._load_quotes([code], symbol).get(code)
        if quote is None:
            raise DataFetchError("TickPlus quote unavailable for requested target")
        return deepcopy(quote)

    def prefetch_realtime_quotes(self, stock_codes, batch_size=100):
        groups = {"stock": [], "etf": []}
        for stock_code in stock_codes:
            try:
                code, symbol = self._symbol(stock_code)
            except DataFetchError:
                continue
            if code not in groups[symbol]:
                groups[symbol].append(code)
        size = max(1, min(int(batch_size), 100))
        count = 0
        for symbol, codes in groups.items():
            for start in range(0, len(codes), size):
                count += len(self._load_quotes(codes[start:start + size], symbol))
        return count

    def get_stock_name(self, stock_code):
        code, symbol = self._symbol(stock_code)
        with self._lock:
            if symbol not in self._loaded_name_symbols:
                rows = self._request("list", symbol=symbol)
                self._names.update({str(r["code"]): str(r["name"]) for r in rows
                                    if r.get("code") and r.get("name")})
                if rows:
                    self._loaded_name_symbols.add(symbol)
            return self._names.get(code)
