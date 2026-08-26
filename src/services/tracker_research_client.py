# -*- coding: utf-8 -*-
"""Safe DSA client for Tracker's local Korean-stock research sidecar.

Tracker owns provider credentials, refresh scheduling, and its isolated cache.
This module is the single DSA boundary for that sidecar: it accepts only a
loopback endpoint, bounds every response, redacts provider failures into
stable reason codes, and never exposes the bearer token outside the backend.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen


TRACKER_RESEARCH_BUNDLE_VERSION = "tracker-research-bundle/v1"
TRACKER_RESEARCH_BUNDLE_SOURCE = "tracker_research_bundle"
TRACKER_RESEARCH_MAX_RESPONSE_BYTES = 128 * 1024
TRACKER_RESEARCH_REFRESH_MAX_RESPONSE_BYTES = 16 * 1024
TRACKER_RESEARCH_REFRESH_POLL_SECONDS = 0.5
TRACKER_RESEARCH_BLOCK_SOURCES = (
    "MARKET_DATA",
    "DART",
    "FLOW_DATA",
    "KRX_STATUS",
    "DISCLOSURE_HEADLINES",
    "NEWS_HEADLINES",
)

_TRACKER_TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9._~+/=:-]{32,512}$")
_KRX_TICKER_PATTERN = re.compile(
    r"^(?P<symbol>\d{6})\.(?P<suffix>KS|KQ)$", re.IGNORECASE
)
_REFRESH_JOB_STATUSES = {"QUEUED", "RUNNING", "SUCCEEDED", "FAILED"}


@dataclass(frozen=True)
class TrackerResearchTarget:
    """Canonical KRX target supported by Tracker's private sidecar."""

    symbol: str
    suffix: str
    market: str

    @property
    def ticker(self) -> str:
        return f"{self.symbol}.{self.suffix}"


@dataclass(frozen=True)
class TrackerResearchSettings:
    """Validated private settings used only by DSA backend processes."""

    base_url: str
    bearer_token: str
    timeout_s: float
    preflight_enabled: bool
    refresh_wait_s: float


@dataclass(frozen=True)
class TrackerNewsEvidence:
    """Bounded news evidence extracted from an already-validated bundle."""

    symbol: str
    market: str
    status: str
    captured_at: Optional[str]
    provider_identity: Optional[str]
    headlines: Tuple[Dict[str, str], ...]

    @property
    def count(self) -> int:
        return len(self.headlines)

    @property
    def dedupe_key(self) -> str:
        return ":".join(
            (
                "tracker_news",
                self.symbol,
                self.market,
                self.captured_at or "unknown",
                self.status,
            )
        )


def tracker_research_target(stock_code: Any) -> Optional[TrackerResearchTarget]:
    """Return a canonical Tracker target only for explicit .KS/.KQ tickers."""
    match = _KRX_TICKER_PATTERN.fullmatch(str(stock_code or "").strip())
    if match is None:
        return None
    suffix = match.group("suffix").upper()
    return TrackerResearchTarget(
        symbol=match.group("symbol"),
        suffix=suffix,
        market="KOSPI" if suffix == "KS" else "KOSDAQ",
    )


def _loopback_tracker_base_url(raw_url: Any) -> Optional[str]:
    """Validate the endpoint once so callers cannot turn this into SSRF."""
    value = str(raw_url or "").strip().rstrip("/")
    if not value:
        return None
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        return None
    hostname = (parsed.hostname or "").lower()
    if (
        parsed.scheme != "http"
        or hostname not in {"127.0.0.1", "localhost", "::1"}
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
        or port is None
        or not 1024 <= port <= 65535
    ):
        return None
    return value


def _bounded_float(value: Any, *, fallback: float, minimum: float, maximum: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return fallback
    if parsed < minimum or parsed > maximum:
        return fallback
    return parsed


def resolve_tracker_research_settings(
    config: Any,
) -> Tuple[Optional[TrackerResearchSettings], str]:
    """Return validated settings or a public-safe configuration reason."""
    token = str(getattr(config, "tracker_research_api_token", "") or "").strip()
    raw_url = getattr(config, "tracker_research_api_url", "")
    if not token and not str(raw_url or "").strip():
        return None, "tracker_research_not_configured"
    base_url = _loopback_tracker_base_url(raw_url)
    if base_url is None or _TRACKER_TOKEN_PATTERN.fullmatch(token) is None:
        return None, (
            "tracker_research_not_configured"
            if not token
            else "tracker_research_configuration_invalid"
        )
    return TrackerResearchSettings(
        base_url=base_url,
        bearer_token=token,
        timeout_s=_bounded_float(
            getattr(config, "tracker_research_api_timeout_s", 8.0),
            fallback=8.0,
            minimum=1.0,
            maximum=30.0,
        ),
        preflight_enabled=bool(
            getattr(config, "tracker_research_preflight_enabled", True)
        ),
        refresh_wait_s=_bounded_float(
            getattr(config, "tracker_research_refresh_wait_s", 8.0),
            fallback=8.0,
            minimum=0.0,
            maximum=30.0,
        ),
    ), ""


def tracker_research_is_configured(config: Any) -> bool:
    """Whether DSA has a valid private sidecar configuration."""
    settings, _reason = resolve_tracker_research_settings(config)
    return settings is not None


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


def _decode_bounded_json(raw: bytes, maximum_bytes: int) -> Optional[dict]:
    if len(raw) > maximum_bytes:
        return None
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _compact_bundle(
    payload: Any,
    *,
    target: TrackerResearchTarget,
    captured_at_or_before: str,
) -> Optional[dict]:
    """Validate the versioned sidecar contract and retain bounded fields only."""
    if (
        not isinstance(payload, dict)
        or payload.get("version") != TRACKER_RESEARCH_BUNDLE_VERSION
        or payload.get("symbol") != target.symbol
        or payload.get("market") != target.market
        or not isinstance(payload.get("blocks"), dict)
    ):
        return None
    compact_blocks: Dict[str, dict] = {}
    for source in TRACKER_RESEARCH_BLOCK_SOURCES:
        block = payload["blocks"].get(source)
        if not isinstance(block, dict) or block.get("source") != source:
            return None
        summary = block.get("normalizedSummary")
        compact_blocks[source] = {
            "status": block.get("status"),
            "reason": block.get("reason"),
            "provider_identity": block.get("providerIdentity"),
            "captured_at": block.get("capturedAt"),
            "as_of_date": block.get("asOfDate"),
            "age_ms": block.get("ageMs"),
            "stale_after_ms": block.get("staleAfterMs"),
            "summary": summary if isinstance(summary, dict) else None,
        }
    return {
        "status": "available",
        "source": TRACKER_RESEARCH_BUNDLE_SOURCE,
        "symbol": target.symbol,
        "market": target.market,
        "captured_at_or_before": payload.get(
            "capturedAtOrBefore", captured_at_or_before
        ),
        "blocks": compact_blocks,
    }


def _unavailable_result(
    reason: str, _target: Optional[TrackerResearchTarget] = None
) -> dict:
    # Keep transient sidecar failures intentionally minimal.  The requested
    # ticker is already known to the caller, and exposing no extra failure
    # payload keeps the Agent-facing contract stable and non-diagnostic.
    return {
        "status": "unavailable",
        "source": TRACKER_RESEARCH_BUNDLE_SOURCE,
        "reason": reason,
    }


class TrackerResearchClient:
    """Small, synchronous backend client with an optional bounded refresh preflight."""

    def __init__(
        self,
        settings: TrackerResearchSettings,
        *,
        open_url: Optional[Callable[..., Any]] = None,
        monotonic: Optional[Callable[[], float]] = None,
        sleep: Optional[Callable[[float], None]] = None,
        now_iso: Optional[Callable[[], str]] = None,
    ) -> None:
        self.settings = settings
        self._open_url = open_url or urlopen
        self._monotonic = monotonic or time.monotonic
        self._sleep = sleep or time.sleep
        self._now_iso = now_iso or _utc_now_iso

    @property
    def is_configured(self) -> bool:
        return True

    def _request_json(
        self,
        *,
        path: str,
        method: str,
        maximum_bytes: int,
        timeout_s: Optional[float] = None,
    ) -> Tuple[Optional[int], Optional[dict]]:
        request = Request(
            f"{self.settings.base_url}{path}",
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {self.settings.bearer_token}",
            },
            data=b"" if method == "POST" else None,
            method=method,
        )
        timeout = self.settings.timeout_s if timeout_s is None else timeout_s
        try:
            with self._open_url(request, timeout=timeout) as response:  # noqa: S310 - loopback URL was validated
                raw = response.read(maximum_bytes + 1)
                status_code = getattr(response, "status", None) or 200
        except HTTPError as error:
            try:
                raw = error.read(maximum_bytes + 1)
            except (OSError, ValueError):
                raw = b""
            return int(error.code), _decode_bounded_json(raw, maximum_bytes)
        except (TimeoutError, URLError, OSError):
            return None, None
        return int(status_code), _decode_bounded_json(raw, maximum_bytes)

    def read_bundle(self, stock_code: Any) -> dict:
        """Read already-stored research only; this method never queues refreshes."""
        target = tracker_research_target(stock_code)
        if target is None:
            return {
                "status": "not_applicable",
                "source": TRACKER_RESEARCH_BUNDLE_SOURCE,
                "reason": "krx_ticker_required",
                "note": "Tracker research supports six-digit .KS and .KQ tickers only.",
            }
        captured_at_or_before = self._now_iso()
        status_code, payload = self._request_json(
            path=(
                f"/v1/research/stocks/{target.ticker}/bundle?"
                f"{urlencode({'capturedAtOrBefore': captured_at_or_before})}"
            ),
            method="GET",
            maximum_bytes=TRACKER_RESEARCH_MAX_RESPONSE_BYTES,
        )
        if status_code == 409 and payload == {"error": "refresh_required"}:
            return {
                "status": "refresh_required",
                "source": TRACKER_RESEARCH_BUNDLE_SOURCE,
                "reason": "tracker_research_refresh_required",
                "symbol": target.symbol,
                "market": target.market,
            }
        if status_code is None:
            return _unavailable_result("tracker_research_unavailable", target)
        if status_code != 200:
            return _unavailable_result("tracker_research_http_error", target)
        compact = _compact_bundle(
            payload,
            target=target,
            captured_at_or_before=captured_at_or_before,
        )
        if compact is None:
            return _unavailable_result("tracker_research_response_invalid", target)
        return compact

    def _enqueue_refresh(self, target: TrackerResearchTarget) -> Tuple[Optional[str], dict]:
        status_code, payload = self._request_json(
            path=f"/v1/research/stocks/{target.ticker}/refresh",
            method="POST",
            maximum_bytes=TRACKER_RESEARCH_REFRESH_MAX_RESPONSE_BYTES,
        )
        if status_code not in {200, 202} or not isinstance(payload, dict):
            return None, _unavailable_result("tracker_research_refresh_unavailable", target)
        status = payload.get("status")
        if status not in _REFRESH_JOB_STATUSES:
            return None, _unavailable_result("tracker_research_refresh_response_invalid", target)
        return str(status), {}

    def _read_refresh_status(
        self, target: TrackerResearchTarget, *, timeout_s: float
    ) -> Tuple[Optional[str], dict]:
        status_code, payload = self._request_json(
            path=f"/v1/research/stocks/{target.ticker}/refresh",
            method="GET",
            maximum_bytes=TRACKER_RESEARCH_REFRESH_MAX_RESPONSE_BYTES,
            timeout_s=timeout_s,
        )
        if status_code not in {200, 202} or not isinstance(payload, dict):
            return None, _unavailable_result("tracker_research_refresh_unavailable", target)
        status = payload.get("status")
        if status not in _REFRESH_JOB_STATUSES:
            return None, _unavailable_result("tracker_research_refresh_response_invalid", target)
        return str(status), {}

    def prepare_bundle(self, stock_code: Any) -> dict:
        """Read a bundle and, only when absent, request bounded sidecar refresh work.

        The refresh job writes exclusively to Tracker's dedicated research cache.
        Provider, cache, and HTTP errors fail open so price/technical analysis can
        continue without a fabricated news conclusion.
        """
        initial = self.read_bundle(stock_code)
        if initial.get("status") != "refresh_required":
            return initial
        if not self.settings.preflight_enabled:
            return initial
        target = tracker_research_target(stock_code)
        if target is None:  # Defensive: read_bundle above already handled this.
            return initial
        job_status, failure = self._enqueue_refresh(target)
        if job_status is None:
            return failure
        if job_status == "SUCCEEDED":
            refreshed = self.read_bundle(stock_code)
            return (
                refreshed
                if refreshed.get("status") == "available"
                else _unavailable_result("tracker_research_refresh_completed_without_bundle", target)
            )
        if job_status == "FAILED":
            return _unavailable_result("tracker_research_refresh_failed", target)

        deadline = self._monotonic() + self.settings.refresh_wait_s
        while True:
            remaining = deadline - self._monotonic()
            if remaining <= 0:
                return _unavailable_result("tracker_research_refresh_pending", target)
            self._sleep(min(TRACKER_RESEARCH_REFRESH_POLL_SECONDS, remaining))
            remaining = deadline - self._monotonic()
            if remaining <= 0:
                return _unavailable_result("tracker_research_refresh_pending", target)
            job_status, failure = self._read_refresh_status(
                target,
                timeout_s=min(self.settings.timeout_s, max(0.1, remaining)),
            )
            if job_status is None:
                return failure
            if job_status in {"QUEUED", "RUNNING"}:
                continue
            if job_status == "FAILED":
                return _unavailable_result("tracker_research_refresh_failed", target)
            refreshed = self.read_bundle(stock_code)
            return (
                refreshed
                if refreshed.get("status") == "available"
                else _unavailable_result("tracker_research_refresh_completed_without_bundle", target)
            )


def create_tracker_research_client(config: Any) -> Tuple[Optional[TrackerResearchClient], str]:
    """Build a backend client without ever returning private configuration values."""
    settings, reason = resolve_tracker_research_settings(config)
    return (TrackerResearchClient(settings), "") if settings is not None else (None, reason)


def tracker_news_evidence_from_bundle(result: Any) -> Optional[TrackerNewsEvidence]:
    """Extract up to five valid headline records from a compact sidecar bundle."""
    if not isinstance(result, dict) or result.get("status") != "available":
        return None
    symbol = result.get("symbol")
    market = result.get("market")
    blocks = result.get("blocks")
    if not isinstance(symbol, str) or not isinstance(market, str) or not isinstance(blocks, dict):
        return None
    block = blocks.get("NEWS_HEADLINES")
    if not isinstance(block, dict):
        return None
    status = block.get("status")
    summary = block.get("summary")
    if status not in {"FRESH", "STALE"} or not isinstance(summary, dict):
        return TrackerNewsEvidence(
            symbol=symbol,
            market=market,
            status=str(status or "UNAVAILABLE"),
            captured_at=(
                block.get("captured_at")
                if isinstance(block.get("captured_at"), str)
                else None
            ),
            provider_identity=(
                block.get("provider_identity")
                if isinstance(block.get("provider_identity"), str)
                else None
            ),
            headlines=(),
        )
    raw_headlines = summary.get("headlines")
    headlines: List[Dict[str, str]] = []
    if isinstance(raw_headlines, list):
        for raw_headline in raw_headlines:
            if not isinstance(raw_headline, dict):
                continue
            title = _bounded_text(raw_headline.get("title"), 240)
            if not title:
                continue
            headline = {"title": title}
            for key, maximum in (
                ("description", 400),
                ("publisher", 120),
                ("publishedAt", 64),
                ("sourceDomain", 160),
                ("category", 64),
                ("sentiment", 64),
                ("importance", 64),
            ):
                value = _bounded_text(raw_headline.get(key), maximum)
                if value:
                    headline[key] = value
            headlines.append(headline)
            if len(headlines) == 5:
                break
    return TrackerNewsEvidence(
        symbol=symbol,
        market=market,
        status=str(status),
        captured_at=(
            block.get("captured_at")
            if isinstance(block.get("captured_at"), str)
            else None
        ),
        provider_identity=(
            block.get("provider_identity")
            if isinstance(block.get("provider_identity"), str)
            else None
        ),
        headlines=tuple(headlines),
    )


def _bounded_text(value: Any, maximum: int) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.split())[:maximum]


def tracker_news_headline_count(result: Any) -> int:
    """Return the number of actual Tracker headlines supplied in this bundle."""
    evidence = tracker_news_evidence_from_bundle(result)
    return evidence.count if evidence is not None else 0


def tracker_news_evidence_key(result: Any) -> Optional[str]:
    """Stable source key for per-run Agent evidence de-duplication."""
    evidence = tracker_news_evidence_from_bundle(result)
    return evidence.dedupe_key if evidence is not None else None


def iter_tracker_news_headlines(result: Any) -> Iterable[Dict[str, str]]:
    """Expose only bounded, validated headline metadata to report builders."""
    evidence = tracker_news_evidence_from_bundle(result)
    return () if evidence is None else evidence.headlines
