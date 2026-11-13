# -*- coding: utf-8 -*-
"""Service orchestration for market sentiment snapshots (issue #1939 Wave 4).

Coordinates fetch -> compute -> persist for one trade date and owns the
trigger semantics from the implementation plan §4.1:

- trigger target is ALWAYS the latest CLOSED trade date, resolved in a fixed
  ``Asia/Shanghai`` timezone (never the host timezone): now >= 15:00 on a
  trade day -> that day, otherwise the previous trade day;
- an explicit ``trade_date`` must equal the resolved target exactly
  (``InvalidTargetDateError`` otherwise — no future dates, no arbitrary
  historical backfill; spot-derived metrics are only valid for "today");
- ``prev_trade_date`` is the previous TRADE day (Friday for Monday targets),
  never natural day -1;
- the M6 turnover MoM denominator is read back from the snapshot table's own
  row at ``prev_trade_date`` (cold start -> null + ``missing_prev``);
- an existing ``complete`` snapshot short-circuits the trigger unless
  ``force=True`` (no fetch cost);
- a global in-process lock (the ``trigger_market_review`` lock-token pattern)
  rejects concurrent triggers; cross-process races are bounded by the
  storage-layer unique constraint (§3.4 rule 5);
- ``run_snapshot_job`` is fully fail-open: internal errors are logged, never
  raised — a snapshot is persisted as ``partial`` whenever any data arrived.

Six module-level functions mirror the Wave 4 signature contract (Wave 5 maps
API endpoints onto them mechanically).
"""

from __future__ import annotations

import json
import logging
import threading
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import pandas as pd
from zoneinfo import ZoneInfo

from data_provider.akshare_fetcher import _akshare_call_with_timeout
from data_provider.market_sentiment_fetcher import MarketSentimentFetcher
from src.core.market_sentiment_metrics import (
    REQUIRED_GROUPS,
    compute_breadth,
    compute_broken_pool,
    compute_limit_up_section,
    compute_prev_feedback,
    compute_promotion,
    compute_sector_strength,
    compute_turnover,
    derive_metric_status,
)
from src.repositories.market_sentiment_repo import (
    METRIC_STATUS_TO_SECTION,
    QUALITY_STATUS_COMPLETE,
    MarketSentimentRepository,
)
from src.storage import MarketSentimentSnapshot

logger = logging.getLogger(__name__)

MARKET_CN = "cn"
SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")
CLOSE_CUTOFF = time(15, 0)  # 收盘门：>=15:00 当日才算已收盘交易日
DEFAULT_TREND_DAYS = 30
DEFAULT_CALENDAR_TIMEOUT_SECONDS = 30.0

API_TRADE_CALENDAR = "ak.tool_trade_date_hist_sina"


def _resolve_fetch_timeout_seconds() -> Optional[float]:
    """MARKET_SENTIMENT_FETCH_TIMEOUT_SECONDS 配置缝（issue #1939 Wave 6）。

    读取 Config 单例的 ``market_sentiment_fetch_timeout_seconds``（默认 45，
    env 解析期已钳制 5~300）；任何配置读取失败一律返回 None，让 fetcher
    使用内置默认 45s（与 W3 交付行为一致，fail-open 不阻断触发）。
    """
    try:
        from src.config import get_config

        value = getattr(get_config(), "market_sentiment_fetch_timeout_seconds", None)
        if value is None:
            return None
        return float(value)
    except Exception as exc:  # pragma: no cover - 配置不可用时的兜底路径
        logger.warning("[MarketSentiment] 取数超时配置不可用，回退内置默认 45s: %s", exc)
        return None


# ---------------------------------------------------------------------------
# errors
# ---------------------------------------------------------------------------

class TradeCalendarUnavailableError(RuntimeError):
    """交易日历不可用（网络失败/为空），无法解析触发目标。"""


class InvalidTargetDateError(ValueError):
    """显式 trade_date 与解析出的唯一可触发目标日不一致。"""


class SnapshotTriggerConflictError(RuntimeError):
    """全局触发锁被占用（已有快照任务在执行）。"""


# ---------------------------------------------------------------------------
# result models (Wave 5 maps these onto API schemas)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SnapshotSummary:
    trade_date: str
    quality_status: str
    completeness: float
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


@dataclass(frozen=True)
class TriggerResult:
    status: str  # 'accepted' | 'short_circuited'
    trade_date: str
    task_id: Optional[str] = None
    existing_snapshot_summary: Optional[Dict[str, Any]] = None


@dataclass(frozen=True)
class SnapshotRecord:
    trade_date: str
    market: str
    quality_status: str
    completeness: float
    payload: Dict[str, Any] = field(default_factory=dict)
    provider_trace: List[Dict[str, Any]] = field(default_factory=list)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


@dataclass(frozen=True)
class ListResult:
    items: List[SnapshotSummary]
    total: int


@dataclass(frozen=True)
class TrendPoint:
    trade_date: str
    value: Optional[float]
    quality_status: str


@dataclass(frozen=True)
class TrendResult:
    metric: str
    points: List[TrendPoint]
    available_points: int


# ---------------------------------------------------------------------------
# trade-date helpers
# ---------------------------------------------------------------------------

def _now_shanghai() -> datetime:
    """Current time in the fixed Asia/Shanghai timezone (test seam)."""
    return datetime.now(SHANGHAI_TZ)


def _as_shanghai(value: datetime) -> datetime:
    """Naive datetimes are treated as Asia/Shanghai; aware ones converted."""
    if value.tzinfo is None:
        return value.replace(tzinfo=SHANGHAI_TZ)
    return value.astimezone(SHANGHAI_TZ)


def _parse_trade_date(value: Any) -> date:
    """Accept date/datetime/'YYYY-MM-DD'/'YYYYMMDD'; raise ValueError else."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    for fmt in ("%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"invalid trade_date format: {value!r} (expected YYYY-MM-DD)")


_CALENDAR_CACHE: Dict[str, Any] = {"loaded_on": None, "dates": None}


def _load_trade_dates() -> List[date]:
    """Load the SSE trade calendar via akshare (sina), cached per natural day.

    Raises ``TradeCalendarUnavailableError`` on any failure — an honest
    failure beats guessing a holiday as a trade day.
    """
    today = _now_shanghai().date()
    if _CALENDAR_CACHE["loaded_on"] == today and _CALENDAR_CACHE["dates"]:
        return list(_CALENDAR_CACHE["dates"])
    try:
        import akshare as ak

        raw = _akshare_call_with_timeout(
            ak.tool_trade_date_hist_sina,
            timeout=DEFAULT_CALENDAR_TIMEOUT_SECONDS,
            call_name=API_TRADE_CALENDAR,
        )
        if raw is None or getattr(raw, "empty", True) or "trade_date" not in raw.columns:
            raise TradeCalendarUnavailableError(
                f"{API_TRADE_CALENDAR} returned no usable trade dates"
            )
        series = pd.to_datetime(raw["trade_date"], errors="coerce").dropna()
        dates = sorted({ts.date() for ts in series})
        if not dates:
            raise TradeCalendarUnavailableError(
                f"{API_TRADE_CALENDAR} returned no parseable trade dates"
            )
    except TradeCalendarUnavailableError:
        raise
    except Exception as exc:  # timeout / network / parser errors
        raise TradeCalendarUnavailableError(
            f"failed to load trade calendar via {API_TRADE_CALENDAR}: {exc}"
        ) from exc
    _CALENDAR_CACHE["loaded_on"] = today
    _CALENDAR_CACHE["dates"] = list(dates)
    return list(dates)


def _resolve_latest_closed(now_sh: datetime, trade_dates: Sequence[date]) -> date:
    """§4.1: >=15:00 且当日交易日 → 当日；否则上一交易日。"""
    today = now_sh.date()
    if today in set(trade_dates) and now_sh.time() >= CLOSE_CUTOFF:
        return today
    earlier = [d for d in trade_dates if d < today]
    if not earlier:
        raise TradeCalendarUnavailableError(
            "trade calendar has no closed trade day before " + today.isoformat()
        )
    return max(earlier)


def _prev_trade_date(target: date, trade_dates: Sequence[date]) -> Optional[date]:
    """Previous TRADE day strictly before ``target`` (Friday for Monday)."""
    earlier = [d for d in trade_dates if d < target]
    return max(earlier) if earlier else None


# ---------------------------------------------------------------------------
# global trigger lock (trigger_market_review lock-token pattern, in-process)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class TriggerLockToken:
    task_id: str
    trade_date: str
    acquired_at: datetime


_TRIGGER_GUARD = threading.Lock()
_TRIGGER_ACTIVE: Optional[TriggerLockToken] = None


def _try_acquire_trigger_lock(trade_date: str) -> Optional[TriggerLockToken]:
    global _TRIGGER_ACTIVE
    with _TRIGGER_GUARD:
        if _TRIGGER_ACTIVE is not None:
            return None
        token = TriggerLockToken(
            task_id=uuid.uuid4().hex,
            trade_date=trade_date,
            acquired_at=_now_shanghai(),
        )
        _TRIGGER_ACTIVE = token
        return token


def _release_trigger_lock() -> None:
    """Release the global trigger lock (idempotent; safe when not held)."""
    global _TRIGGER_ACTIVE
    with _TRIGGER_GUARD:
        _TRIGGER_ACTIVE = None


#: 公开别名：Wave 5 在 submit_background_task 失败的兜底路径中调用，
#: 防止 accepted 后未入队导致锁泄漏。
release_snapshot_trigger_lock = _release_trigger_lock


# ---------------------------------------------------------------------------
# trend metric registry (§4.4 enum -> payload section + extractor)
# ---------------------------------------------------------------------------

TREND_METRICS: Dict[str, Tuple[str, Callable[[Dict[str, Any]], Any]]] = {
    "advance_decline_diff": ("breadth", lambda s: s.get("advance_decline_diff")),
    "turnover_mom": ("turnover", lambda s: s.get("mom_change_pct")),
    "limit_up_count": ("limit_up", lambda s: s.get("count")),
    "failure_rate": ("broken_limit", lambda s: s.get("failure_rate")),
    "max_boards": ("limit_up", lambda s: s.get("max_boards")),
    "overall_promotion_rate": (
        "promotion", lambda s: (s.get("overall") or {}).get("rate"),
    ),
    "feedback_avg_change_pct": (
        "yesterday_limit_feedback", lambda s: s.get("avg_change_pct"),
    ),
}


def _row_to_summary(row: MarketSentimentSnapshot) -> SnapshotSummary:
    return SnapshotSummary(
        trade_date=row.trade_date,
        quality_status=row.quality_status,
        completeness=float(row.completeness or 0.0),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _row_to_record(row: MarketSentimentSnapshot) -> SnapshotRecord:
    try:
        payload = json.loads(row.payload) if row.payload else {}
    except (TypeError, ValueError):
        payload = {}
    try:
        trace = json.loads(row.provider_trace) if row.provider_trace else []
    except (TypeError, ValueError):
        trace = []
    return SnapshotRecord(
        trade_date=row.trade_date,
        market=row.market,
        quality_status=row.quality_status,
        completeness=float(row.completeness or 0.0),
        payload=payload if isinstance(payload, dict) else {},
        provider_trace=trace if isinstance(trace, list) else [],
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


# ---------------------------------------------------------------------------
# service
# ---------------------------------------------------------------------------

class MarketSentimentService:
    """Orchestrates one snapshot run: fetch -> metrics -> save (fail-open)."""

    def __init__(
        self,
        repo: Optional[MarketSentimentRepository] = None,
        fetcher_factory: Optional[Callable[[], Any]] = None,
        trade_dates_provider: Optional[Callable[[], List[date]]] = None,
    ):
        self._repo = repo
        self._fetcher_factory = fetcher_factory
        self._trade_dates_provider = trade_dates_provider

    # -- dependency seams ---------------------------------------------------

    def _get_repo(self) -> MarketSentimentRepository:
        if self._repo is None:
            self._repo = MarketSentimentRepository()
        return self._repo

    def _build_fetcher(self) -> Any:
        if self._fetcher_factory is not None:
            return self._fetcher_factory()
        # Wave 6 配置接线（issue #1939）：MARKET_SENTIMENT_FETCH_TIMEOUT_SECONDS
        # （默认 45，钳制 5~300，由 Config 解析）传入池接口子进程超时；
        # 配置不可用时返回 None → fetcher 使用内置默认 45s，行为与 W3 交付一致。
        return MarketSentimentFetcher(timeout=_resolve_fetch_timeout_seconds())

    def _get_trade_dates(
        self, override: Optional[Callable[[], List[date]]] = None
    ) -> List[date]:
        provider = override or self._trade_dates_provider
        if provider is None:
            provider = _load_trade_dates  # module global（monkeypatch seam）
        return list(provider())

    def _get_trade_dates_fail_open(self) -> List[date]:
        try:
            return self._get_trade_dates()
        except TradeCalendarUnavailableError as exc:
            logger.warning(
                "[MarketSentiment] 交易日历不可用，prev_trade_date 置空（fail-open）: %s", exc
            )
            return []

    # -- 1. trigger target resolution ---------------------------------------

    def resolve_latest_closed_trade_date(
        self,
        now: Optional[datetime] = None,
        trade_dates_provider: Optional[Callable[[], List[date]]] = None,
    ) -> date:
        now_sh = _as_shanghai(now if now is not None else _now_shanghai())
        trade_dates = self._get_trade_dates(trade_dates_provider)
        return _resolve_latest_closed(now_sh, trade_dates)

    # -- 2. trigger -----------------------------------------------------------

    def trigger_snapshot(
        self, trade_date: Optional[str] = None, force: bool = False
    ) -> TriggerResult:
        target = self.resolve_latest_closed_trade_date()
        target_iso = target.isoformat()
        if trade_date is not None:
            explicit = _parse_trade_date(trade_date)
            if explicit != target:
                raise InvalidTargetDateError(
                    f"trade_date={explicit.isoformat()} 与唯一可触发目标日 "
                    f"{target_iso} 不一致（目标按 Asia/Shanghai 收盘规则解析："
                    "≥15:00 且当日交易日为当日，否则上一交易日）"
                )
        if not force:
            existing = self._get_repo().get_by_market_date(MARKET_CN, target_iso)
            if existing is not None and existing.quality_status == QUALITY_STATUS_COMPLETE:
                summary = _row_to_summary(existing)
                logger.info(
                    "[MarketSentiment] 已有 complete 快照，短路返回 trade_date=%s", target_iso
                )
                return TriggerResult(
                    status="short_circuited",
                    trade_date=target_iso,
                    existing_snapshot_summary={
                        "trade_date": summary.trade_date,
                        "quality_status": summary.quality_status,
                        "completeness": summary.completeness,
                        "updated_at": (
                            summary.updated_at.isoformat()
                            if summary.updated_at else None
                        ),
                    },
                )
        token = _try_acquire_trigger_lock(target_iso)
        if token is None:
            raise SnapshotTriggerConflictError(
                "情绪快照任务正在执行中（全局锁冲突），请稍后再试"
            )
        logger.info(
            "[MarketSentiment] 触发已接受 trade_date=%s task_id=%s",
            target_iso, token.task_id,
        )
        return TriggerResult(status="accepted", trade_date=target_iso, task_id=token.task_id)

    # -- 3. background job body ------------------------------------------------

    def run_snapshot_job(self, trade_date: str) -> None:
        """后台任务体：fetch → compute → save_snapshot，全链 fail-open 不抛。"""
        try:
            target_date = _parse_trade_date(trade_date)
        except ValueError:
            logger.error(
                "[MarketSentiment] run_snapshot_job 收到无法解析的 trade_date=%r，跳过", trade_date
            )
            _release_trigger_lock()
            return
        try:
            self._execute_snapshot(target_date)
        except Exception:
            logger.exception(
                "[MarketSentiment] 快照任务内部异常 trade_date=%s（fail-open，不向上抛出）",
                target_date.isoformat(),
            )
        finally:
            _release_trigger_lock()

    def _execute_snapshot(self, target_date: date) -> None:
        iso = target_date.isoformat()
        compact = iso.replace("-", "")

        trade_dates = self._get_trade_dates_fail_open()
        prev_date = _prev_trade_date(target_date, trade_dates)
        prev_iso = prev_date.isoformat() if prev_date else None
        prev_compact = prev_iso.replace("-", "") if prev_iso else None

        prev_total_amount = self._lookup_prev_total_amount(prev_iso)
        fetcher = self._build_fetcher()
        fetched = fetcher.fetch_all(compact, prev_compact)

        sections = self._compute_sections(fetched, prev_iso, prev_total_amount)
        metric_status = derive_metric_status(sections)
        payload: Dict[str, Any] = {
            "schema_version": 1,
            "market": MARKET_CN,
            "trade_date": iso,
            "prev_trade_date": prev_iso,
            "required_groups": list(REQUIRED_GROUPS),
            "metric_status": metric_status,
            "narrative": None,
            "narrative_generated_at": None,
        }
        for group, section_key in METRIC_STATUS_TO_SECTION.items():
            payload[section_key] = sections[group]

        trace = list(fetched.get("provider_trace") or [])
        result = self._get_repo().save_snapshot(payload, trace, market=MARKET_CN, trade_date=iso)
        logger.info(
            "[MarketSentiment] 快照落库 trade_date=%s action=%s quality=%s completeness=%.3f",
            iso, result.action, result.snapshot.quality_status, result.snapshot.completeness,
        )

    def _compute_sections(
        self,
        fetched: Dict[str, Any],
        prev_iso: Optional[str],
        prev_total_amount: Optional[float],
    ) -> Dict[str, Dict[str, Any]]:
        today_pool = fetched.get("today_pool")
        limit_up_count = int(len(today_pool)) if today_pool is not None else None
        return {
            "breadth": compute_breadth(fetched.get("stats")),
            "limit_up_pool": compute_limit_up_section(
                today_pool, fetched.get("limit_down_pool"), fetched.get("stats")
            ),
            "broken_pool": compute_broken_pool(fetched.get("broken_pool"), limit_up_count),
            "turnover": compute_turnover(fetched.get("stats"), prev_total_amount),
            "promotion": compute_promotion(today_pool, fetched.get("prev_pool"), prev_iso),
            "prev_feedback": compute_prev_feedback(fetched.get("previous_pool")),
            "sector": compute_sector_strength(fetched.get("sector_rankings")),
        }

    def _lookup_prev_total_amount(self, prev_iso: Optional[str]) -> Optional[float]:
        """M6 环比分母：回查快照表上一"交易日"自身记录；缺失 → 冷启动 None。"""
        if not prev_iso:
            return None
        row = self._get_repo().get_by_market_date(MARKET_CN, prev_iso)
        if row is None:
            return None
        try:
            payload = json.loads(row.payload) if row.payload else {}
        except (TypeError, ValueError):
            return None
        value = (payload.get("turnover") or {}).get("total_amount_yi")
        if isinstance(value, (int, float)):
            return float(value)
        return None

    # -- 4/5/6. read paths -------------------------------------------------------

    def get_snapshot(self, trade_date: str) -> Optional[SnapshotRecord]:
        iso = _parse_trade_date(trade_date).isoformat()
        row = self._get_repo().get_by_market_date(MARKET_CN, iso)
        return _row_to_record(row) if row is not None else None

    def list_snapshots(
        self, limit: int = 30, offset: int = 0, order: str = "desc"
    ) -> ListResult:
        rows, total = self._get_repo().list_snapshots(
            MARKET_CN, limit=limit, offset=offset, order=order
        )
        return ListResult(items=[_row_to_summary(r) for r in rows], total=int(total))

    def query_trend(
        self,
        metric: str,
        days: Optional[int] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> TrendResult:
        if metric not in TREND_METRICS:
            raise ValueError(
                f"invalid metric: {metric!r}; supported: {sorted(TREND_METRICS)}"
            )
        section_key, extractor = TREND_METRICS[metric]

        start_iso = (
            _parse_trade_date(start_date).isoformat() if start_date else None
        )
        end_iso = _parse_trade_date(end_date).isoformat() if end_date else None

        if start_iso is None or end_iso is None:
            # days 模式（或只给了单端）：end 钳制在 min(今天(上海), 最新快照日)，
            # 未来行永不进入趋势序列；start = end - (days-1) 自然日。
            resolved_end = end_iso or self._default_trend_end()
            if resolved_end is None:
                return TrendResult(metric=metric, points=[], available_points=0)
            window = int(days) if days is not None else DEFAULT_TREND_DAYS
            window = max(1, window)
            end_iso = resolved_end
            if start_iso is None:
                start_iso = (
                    _parse_trade_date(resolved_end) - timedelta(days=window - 1)
                ).isoformat()

        rows = self._get_repo().query_trend_range(
            MARKET_CN, start_date=start_iso, end_date=end_iso
        )
        points: List[TrendPoint] = []
        for row in rows:
            try:
                payload = json.loads(row.payload) if row.payload else {}
            except (TypeError, ValueError):
                payload = {}
            section = payload.get(section_key) or {}
            points.append(
                TrendPoint(
                    trade_date=row.trade_date,
                    value=extractor(section),
                    quality_status=row.quality_status,
                )
            )
        return TrendResult(metric=metric, points=points, available_points=len(points))

    def _default_trend_end(self) -> Optional[str]:
        """min(上海今天, 最新快照日)；无快照 → None。"""
        today_iso = _now_shanghai().date().isoformat()
        rows, _total = self._get_repo().list_snapshots(MARKET_CN, limit=1, order="desc")
        if not rows:
            return None
        latest = rows[0].trade_date
        return min(today_iso, latest)


# ---------------------------------------------------------------------------
# module-level contract functions (Wave 4 signature contract, Wave 5 entry)
# ---------------------------------------------------------------------------

_DEFAULT_SERVICE: Optional[MarketSentimentService] = None
_DEFAULT_SERVICE_LOCK = threading.Lock()


def get_market_sentiment_service() -> MarketSentimentService:
    global _DEFAULT_SERVICE
    with _DEFAULT_SERVICE_LOCK:
        if _DEFAULT_SERVICE is None:
            _DEFAULT_SERVICE = MarketSentimentService()
        return _DEFAULT_SERVICE


def resolve_latest_closed_trade_date(now: Optional[datetime] = None) -> date:
    """Asia/Shanghai ≥15:00 且当日交易日 → 当日，否则上一交易日。"""
    return get_market_sentiment_service().resolve_latest_closed_trade_date(now)


def trigger_snapshot(
    trade_date: Optional[str] = None, force: bool = False
) -> TriggerResult:
    """解析触发目标并占用全局锁；显式 trade_date ≠ 目标 → InvalidTargetDateError。

    返回 accepted 后由调用方（Wave 5 端点）经 ``submit_background_task`` 执行
    ``run_snapshot_job(trade_date)``（任务体结束时释放锁）；入队失败时调用
    ``release_snapshot_trigger_lock()`` 防锁泄漏。
    """
    return get_market_sentiment_service().trigger_snapshot(trade_date, force)


def run_snapshot_job(trade_date: str) -> None:
    """后台任务体：fetch → compute → save_snapshot，全链 fail-open。"""
    get_market_sentiment_service().run_snapshot_job(trade_date)


def get_snapshot(trade_date: str) -> Optional[SnapshotRecord]:
    return get_market_sentiment_service().get_snapshot(trade_date)


def list_snapshots(
    limit: int = 30, offset: int = 0, order: str = "desc"
) -> ListResult:
    return get_market_sentiment_service().list_snapshots(limit, offset, order)


def query_trend(
    metric: str,
    days: Optional[int] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> TrendResult:
    return get_market_sentiment_service().query_trend(metric, days, start_date, end_date)
