# -*- coding: utf-8 -*-
"""Cross-asset context assembly service for Issue #1910 (cross-asset-v1).

Boundary rules (maintainer-confirmed):

- Cross-asset signals only calibrate risk appetite and confidence; they are
  never trading instructions.
- ``get_context`` NEVER raises: any assembly failure degrades to a minimal
  ``risk_appetite="unknown"`` context so the main analysis continues
  (fail-open, same semantics as daily_market_context).
- ``risk_appetite`` is a deterministic, threshold-constants-driven vote over
  ``status == "ok"`` items in indices/fx/volatility — no LLM involved. The
  fx voting branch is part of the cross-asset-v1 contract and stays; in
  phase 1 the FX provider is deferred so no fx items are ever fed in.

Phase-1 note: ``sector_links`` ("why should this stock watch these external
assets", including the industry-keyword rules) are deferred to a later PR —
contexts are built with an empty link list while the contract field stays.
"""

from __future__ import annotations

import logging
import math
import threading
import time
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

from src.schemas.cross_asset_context import (
    CROSS_ASSET_GROUPS,
    CrossAssetContext,
    CrossAssetDataQuality,
    CrossAssetGroupQuality,
    CrossAssetItem,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Deterministic voting thresholds (v1 contract; fixed by unit tests)
# ---------------------------------------------------------------------------
MIN_EFFECTIVE_VOTES = 3
NET_RISK_ON_THRESHOLD = 2
NET_RISK_OFF_THRESHOLD = -2
VIX_ELEVATED_LEVEL = 20.0
VIX_HIGH_LEVEL = 25.0
VIX_ELEVATED_VOTE = -1
VIX_HIGH_VOTE = -2

# In-process cache: one full fetch per (market, trade_date) per process.
_CACHE_TTL_SECONDS = 24 * 3600.0

_MARKET_LABELS = {
    "cn": "A股",
    "hk": "港股",
    "us": "美股",
    "jp": "日股",
    "kr": "韩股",
    "tw": "台股",
    "au": "澳股",
}
_VALID_MARKETS = frozenset(_MARKET_LABELS)


def normalize_cross_asset_market(market: Any) -> str:
    normalized = str(market or "").strip().lower()
    return normalized if normalized in _VALID_MARKETS else "cn"


def _is_non_finite(number: Optional[float]) -> bool:
    return number is not None and not math.isfinite(number)


def sanitize_non_finite_items(
    snapshot: Dict[str, Dict[str, CrossAssetItem]],
) -> Dict[str, Dict[str, CrossAssetItem]]:
    """OR-COR-be3a04e3: mark non-finite ok items invalid BEFORE any consumer.

    Single entry-point filter applied before voting / summary / quality
    stats / caching: an ``status="ok"`` item carrying a non-finite ``value``
    or ``change_pct`` (+/-inf survive ``dropna()``; NaN can leak through
    ``change_pct`` math) used to cast a valid vote, enter the summary and
    quality counts and get cached. Such an item is rebuilt as an explicit
    ``status="error"`` / ``error="non_finite_value"`` item with the numeric
    fields cleared, so the quality quadruple reports the problem instead of
    hiding it. Finite items (and error/not_supported items) pass through
    untouched; the input snapshot is never mutated.
    """

    sanitized: Dict[str, Dict[str, CrossAssetItem]] = {}
    replaced = False
    for group in CROSS_ASSET_GROUPS:
        items = snapshot.get(group) or {}
        cleaned: Dict[str, CrossAssetItem] = {}
        for key, item in items.items():
            if item.status == "ok" and (
                _is_non_finite(item.value) or _is_non_finite(item.change_pct)
            ):
                cleaned[key] = item.model_copy(
                    update={
                        "status": "error",
                        "error": "non_finite_value",
                        "value": None,
                        "change_pct": None,
                    }
                )
                replaced = True
            else:
                cleaned[key] = item
        sanitized[group] = cleaned
    return sanitized if replaced else snapshot


def compute_risk_appetite(snapshot: Dict[str, Dict[str, CrossAssetItem]]) -> Tuple[str, int, int]:
    """Deterministic risk_appetite vote.

    Returns ``(risk_appetite, net_votes, effective_votes)``.
    Voting universe: ``status == "ok"`` items in indices/fx/volatility.

    - indices: change_pct > 0 → +1 (risk-on), < 0 → -1 (risk-off)
    - fx (USD-based pairs): change_pct > 0 (USD stronger / local weaker) → -1,
      < 0 → +1
    - volatility (VIX): level >= 25 → -2; 20 <= level < 25 → -1; below → no vote

    ``unknown`` when effective votes < MIN_EFFECTIVE_VOTES or both the
    indices and volatility groups have no ok items.
    """

    net = 0
    effective = 0
    indices_has_ok = False
    volatility_has_ok = False

    for key, item in (snapshot.get("indices") or {}).items():
        if item.status != "ok" or item.change_pct is None:
            continue
        indices_has_ok = True
        if item.change_pct > 0:
            net += 1
            effective += 1
        elif item.change_pct < 0:
            net -= 1
            effective += 1

    for _key, item in (snapshot.get("fx") or {}).items():
        if item.status != "ok" or item.change_pct is None:
            continue
        if item.change_pct > 0:
            net -= 1
            effective += 1
        elif item.change_pct < 0:
            net += 1
            effective += 1

    for _key, item in (snapshot.get("volatility") or {}).items():
        if item.status != "ok" or item.value is None:
            continue
        volatility_has_ok = True
        if item.value >= VIX_HIGH_LEVEL:
            net += VIX_HIGH_VOTE
            effective += 1
        elif item.value >= VIX_ELEVATED_LEVEL:
            net += VIX_ELEVATED_VOTE
            effective += 1

    if effective < MIN_EFFECTIVE_VOTES or (not indices_has_ok and not volatility_has_ok):
        return "unknown", net, effective
    if net <= NET_RISK_OFF_THRESHOLD:
        return "risk_off", net, effective
    if net >= NET_RISK_ON_THRESHOLD:
        return "risk_on", net, effective
    return "neutral", net, effective


def _format_value(value: Optional[float]) -> str:
    if value is None:
        return "n/a"
    if abs(value) >= 1000:
        return f"{value:,.0f}"
    return f"{value:,.2f}"


def _format_signal(key: str, item: CrossAssetItem) -> Optional[str]:
    if item.status != "ok" or item.value is None:
        return None
    label = item.name or key
    change = ""
    if item.change_pct is not None:
        change = f"({item.change_pct:+.2f}%)"
    return f"{label} {_format_value(item.value)}{change}"


def build_impact_summary(
    market: str,
    risk_appetite: str,
    snapshot: Dict[str, Dict[str, CrossAssetItem]],
    effective_votes: int,
) -> str:
    """Deterministic zh template; no LLM involved."""

    market_label = _MARKET_LABELS.get(normalize_cross_asset_market(market), "A股")
    signals: List[str] = []
    vix_item = (snapshot.get("volatility") or {}).get("VIX")
    if vix_item is not None:
        text = _format_signal("VIX", vix_item)
        if text:
            signals.append(text)
    index_signals = []
    for key, item in (snapshot.get("indices") or {}).items():
        text = _format_signal(key, item)
        if text:
            index_signals.append((abs(item.change_pct or 0.0), text))
    index_signals.sort(reverse=True)
    signals.extend(text for _weight, text in index_signals[:2])
    for key, item in (snapshot.get("fx") or {}).items():
        if item.status == "ok" and item.value is not None:
            text = _format_signal(key, item)
            if text:
                signals.append(text)
                break
    signals_text = "，".join(signals[:3]) if signals else "有效外部数据不足"

    if risk_appetite == "risk_off":
        return (
            f"外部环境偏 risk-off：{signals_text}；"
            f"对本次{market_label}分析构成拖累，宜控制激进度并降低仓位进攻性。"
        )
    if risk_appetite == "risk_on":
        return f"外部环境偏 risk-on：{signals_text}；外部环境总体支持本次{market_label}分析。"
    if risk_appetite == "neutral":
        return f"外部环境信号中性：{signals_text}；暂无明确方向性指引。"
    return f"外部环境信号不足（有效信号 {effective_votes} 项，阈值 {MIN_EFFECTIVE_VOTES} 项），跨资产方向暂不可判。"


def build_risk_tags(
    risk_appetite: str,
    snapshot: Dict[str, Dict[str, CrossAssetItem]],
) -> List[str]:
    tags: List[str] = []
    vix_item = (snapshot.get("volatility") or {}).get("VIX")
    if vix_item is not None and vix_item.status == "ok" and vix_item.value is not None:
        if vix_item.value >= VIX_HIGH_LEVEL:
            tags.append("vix_high")
        elif vix_item.value >= VIX_ELEVATED_LEVEL:
            tags.append("vix_elevated")
    if any(
        item.status == "ok" and (item.change_pct or 0.0) > 0
        for item in (snapshot.get("fx") or {}).values()
    ):
        tags.append("usd_strength")
    down_indices = sum(
        1
        for item in (snapshot.get("indices") or {}).values()
        if item.status == "ok" and (item.change_pct or 0.0) < 0
    )
    if down_indices >= 2:
        tags.append("equities_broad_down")
    if risk_appetite == "unknown":
        tags.append("data_limited")
    return tags


def build_data_quality(snapshot: Dict[str, Dict[str, CrossAssetItem]]) -> CrossAssetDataQuality:
    quality = CrossAssetDataQuality()
    limitations: List[str] = []
    for group in CROSS_ASSET_GROUPS:
        items = snapshot.get(group) or {}
        group_quality = CrossAssetGroupQuality(item_count=len(items))
        sources: List[str] = []
        as_of_values: List[str] = []
        errors: List[str] = []
        for item in items.values():
            if item.source:
                sources.append(item.source)
            if item.as_of:
                as_of_values.append(item.as_of)
            if item.stale:
                group_quality.stale = True
            if item.error:
                errors.append(item.error)
            if item.status == "ok":
                group_quality.ok_count += 1
        if sources:
            group_quality.source = max(set(sources), key=sources.count)
        if as_of_values:
            group_quality.as_of = max(as_of_values)
        if errors:
            group_quality.error = errors[0]
            if len(errors) > 1:
                group_quality.error = f"{group_quality.error} (+{len(errors) - 1} more)"
        if group_quality.item_count > 0 and group_quality.ok_count == 0:
            limitations.append(f"{group}:no_ok_data")
        if group_quality.stale:
            limitations.append(f"{group}:stale_data")
        setattr(quality, group, group_quality)
    quality.limitations = limitations
    return quality


def build_cross_asset_context(
    *,
    market: str,
    trade_date: date,
    snapshot: Dict[str, Dict[str, CrossAssetItem]],
) -> CrossAssetContext:
    """Pure rule engine: snapshot -> CrossAssetContext (no I/O)."""

    # OR-COR-be3a04e3: one entry-point filter before voting, summary,
    # quality stats and the cache — non-finite ok items are marked invalid
    # here so no downstream consumer ever sees them.
    snapshot = sanitize_non_finite_items(snapshot)
    normalized = normalize_cross_asset_market(market)
    risk_appetite, _net, effective_votes = compute_risk_appetite(snapshot)
    return CrossAssetContext(
        market=normalized,
        trade_date=trade_date.isoformat(),
        risk_appetite=risk_appetite,
        indices=dict(snapshot.get("indices") or {}),
        fx=dict(snapshot.get("fx") or {}),
        rates=dict(snapshot.get("rates") or {}),
        commodities=dict(snapshot.get("commodities") or {}),
        crypto=dict(snapshot.get("crypto") or {}),
        volatility=dict(snapshot.get("volatility") or {}),
        impact_summary=build_impact_summary(normalized, risk_appetite, snapshot, effective_votes),
        risk_tags=build_risk_tags(risk_appetite, snapshot),
        data_quality=build_data_quality(snapshot),
    )


def build_minimal_unknown_context(
    *,
    market: Any,
    trade_date: Any,
    reason: str,
) -> CrossAssetContext:
    """Fail-open minimal context; never raises on bad inputs."""

    try:
        normalized = normalize_cross_asset_market(market)
    except Exception:
        normalized = "cn"
    if not isinstance(trade_date, date):
        try:
            trade_date = date.fromisoformat(str(trade_date)[:10])
        except Exception:
            trade_date = date.today()
    return CrossAssetContext(
        market=normalized,
        trade_date=trade_date.isoformat(),
        risk_appetite="unknown",
        impact_summary="跨资产外围数据暂不可用（数据源失败或超时），本次分析不引入跨资产方向参考。",
        risk_tags=["data_limited"],
        data_quality=CrossAssetDataQuality(limitations=[f"cross_asset_context_error:{str(reason)[:120]}"]),
    )


class CrossAssetContextService:
    """Assemble one CrossAssetContext per (market, trade_date); fail-open."""

    def __init__(
        self,
        *,
        fetcher: Any = None,
        config: Any = None,
        cache_ttl_seconds: float = _CACHE_TTL_SECONDS,
    ) -> None:
        self._fetcher = fetcher
        # Explicitly injected fetchers (tests / custom wiring) are sticky:
        # config-driven rebuild below only applies to fetchers this service
        # created itself.
        self._fetcher_injected = fetcher is not None
        # Normalized (timeout, stale) signature of the managed fetcher's
        # creation settings; ``None`` until the service builds one.
        self._fetcher_params: Optional[Tuple[float, int]] = None
        self._config = config
        self._cache_ttl_seconds = float(cache_ttl_seconds)
        self._cache: Dict[Tuple[str, str], Tuple[float, CrossAssetContext]] = {}
        self._lock = threading.Lock()

    def get_context(
        self,
        market: str,
        trade_date: date,
        stock_code: Optional[str] = None,
        *,
        industry: Optional[str] = None,
        config: Any = None,
    ) -> CrossAssetContext:
        """Return the cross-asset context; NEVER raises.

        Disabled switch / any failure → minimal ``risk_appetite="unknown"``
        context (fail-open). ``stock_code`` / ``industry`` are accepted for
        API stability and logged only (industry-driven sector links are
        deferred to a later PR).
        """

        try:
            normalized = normalize_cross_asset_market(market)
            if not isinstance(trade_date, date):
                trade_date = date.fromisoformat(str(trade_date)[:10])
            cache_key = (normalized, trade_date.isoformat())
            cached = self._cache_get(cache_key)
            if cached is not None:
                return cached

            effective_config = config or self._config
            if effective_config is not None and not getattr(
                effective_config, "cross_asset_context_enabled", True
            ):
                context = build_minimal_unknown_context(
                    market=normalized,
                    trade_date=trade_date,
                    reason="cross_asset_context_disabled",
                )
                self._cache_set(cache_key, context)
                return context

            snapshot = self._get_fetcher(effective_config).fetch_market_snapshot(
                normalized, trade_date
            )
            context = build_cross_asset_context(
                market=normalized,
                trade_date=trade_date,
                snapshot=snapshot,
            )
            self._cache_set(cache_key, context)
            return context
        except Exception as exc:
            logger.warning(
                "Cross-asset context assembly failed, falling back to minimal unknown context: %s",
                exc,
                exc_info=True,
            )
            return build_minimal_unknown_context(
                market=market,
                trade_date=trade_date if isinstance(trade_date, date) else None,
                reason=f"{type(exc).__name__}: {exc}",
            )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _get_fetcher(self, config: Any) -> Any:
        if self._fetcher is not None:
            if self._fetcher_injected:
                return self._fetcher
            # Managed fetcher: re-read the timeout/stale settings on every
            # call so a runtime config reload (Web settings page / schedule
            # reload) takes effect without a process restart (PR #2428
            # review). Rebuild only when the effective values actually
            # changed; the per-(market, day) context cache above keeps
            # same-day reads untouched either way.
            if self._fetcher_params == self._resolve_fetcher_params(config):
                return self._fetcher
        from data_provider.cross_asset_fetcher import CrossAssetFetcher

        timeout_seconds = getattr(config, "cross_asset_context_timeout_seconds", 8)
        stale_days = getattr(config, "cross_asset_context_stale_days", 2)
        self._fetcher = CrossAssetFetcher(
            timeout_seconds=timeout_seconds,
            stale_days=stale_days,
        )
        self._fetcher_params = self._resolve_fetcher_params(config)
        return self._fetcher

    @staticmethod
    def _resolve_fetcher_params(config: Any) -> Tuple[float, int]:
        """Normalized (timeout, stale) signature for reload detection.

        Mirrors ``CrossAssetFetcher.__init__`` clamping so equivalent raw
        values (e.g. ``0`` timeout vs the clamped ``1.0``) do not trigger
        pointless rebuilds.
        """
        timeout_seconds = getattr(config, "cross_asset_context_timeout_seconds", 8)
        stale_days = getattr(config, "cross_asset_context_stale_days", 2)
        try:
            timeout_seconds = max(1.0, float(timeout_seconds))
        except (TypeError, ValueError):
            timeout_seconds = 8.0
        try:
            stale_days = max(0, int(stale_days))
        except (TypeError, ValueError):
            stale_days = 2
        return timeout_seconds, stale_days

    def _cache_get(self, key: Tuple[str, str]) -> Optional[CrossAssetContext]:
        with self._lock:
            entry = self._cache.get(key)
            if entry is None:
                return None
            stored_at, context = entry
            if (time.time() - stored_at) > self._cache_ttl_seconds:
                self._cache.pop(key, None)
                return None
            return context

    def _cache_set(self, key: Tuple[str, str], context: CrossAssetContext) -> None:
        now = time.time()
        with self._lock:
            expired = [
                cached_key
                for cached_key, (stored_at, _ctx) in self._cache.items()
                if (now - stored_at) > self._cache_ttl_seconds
            ]
            for cached_key in expired:
                self._cache.pop(cached_key, None)
            self._cache[key] = (now, context)


_default_service: Optional[CrossAssetContextService] = None
_default_service_lock = threading.Lock()


def get_default_cross_asset_context_service() -> CrossAssetContextService:
    """Process-wide service singleton (one fetch per market-day per process)."""

    global _default_service
    if _default_service is None:
        with _default_service_lock:
            if _default_service is None:
                _default_service = CrossAssetContextService()
    return _default_service
