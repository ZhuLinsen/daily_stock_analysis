"""FRED provider for the US macro report; never generates analysis text."""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

import requests
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from src.schemas.macro import MacroObservation

US_FRED_SERIES = {
    "policy_rate_lower": "DFEDTARL", "policy_rate_upper": "DFEDTARU",
    "effective_fed_funds_rate": "DFF", "sofr": "SOFR", "treasury_2y": "DGS2",
    "treasury_10y": "DGS10", "vix": "VIXCLS",
}
FRED_DAILY_STALE_AFTER_DAYS = 7


class FREDProvider:
    def __init__(self, api_key: str, base_url: str = "https://api.stlouisfed.org", session: requests.Session | None = None):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.session = session or requests.Session()

    @retry(retry=retry_if_exception_type(requests.RequestException), stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=4), reraise=True)
    def _get(self, path: str, **params: str) -> dict[str, Any]:
        response = self.session.get(f"{self.base_url}{path}", params={**params, "api_key": self.api_key, "file_type": "json"}, timeout=15)
        response.raise_for_status()
        return response.json()

    def fetch_latest(self, indicator: str, series_id: str) -> MacroObservation | None:
        metadata = self._get("/fred/series", series_id=series_id).get("seriess", [])
        if not metadata:
            return None
        series = metadata[0]
        observations = self._get("/fred/series/observations", series_id=series_id, sort_order="desc", limit="20").get("observations", [])
        valid = next((row for row in observations if row.get("value") not in ("", ".", None)), None)
        now = datetime.now(timezone.utc)
        observation_date = date.fromisoformat(valid["date"]) if valid else None
        is_stale = not bool(valid) or (
            observation_date is not None
            and (now.date() - observation_date).days > FRED_DAILY_STALE_AFTER_DAYS
        )
        return MacroObservation(region="us", indicator=indicator, series_id=series_id, value=float(valid["value"]) if valid else None, unit=series.get("units"), observation_date=observation_date, fetched_at=now, source_name=series.get("source") or "FRED", source_url=f"https://fred.stlouisfed.org/series/{series_id}", frequency=series.get("frequency"), is_stale=is_stale, metadata={"title": series.get("title"), "last_updated": series.get("last_updated")})
