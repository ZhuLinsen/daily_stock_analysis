# -*- coding: utf-8 -*-
"""Repository for market sentiment snapshots (issue #1939 Wave 2).

Implements the idempotent save/merge semantics from the implementation
plan §3.4 for one ``MarketSentimentSnapshot`` row per (market, trade_date):

1. no existing row  -> direct insert (partial or complete both allowed);
2. incoming complete -> full replacement of payload/trace/status/completeness;
3. incoming partial vs existing complete -> keep the complete row untouched
   and flag ``superseded_by_existing_complete`` (row-level comparison only);
4. partial vs partial -> group-level fill-in merge (old ok groups win,
   newly-ok groups fill holes), then recompute completeness/quality_status
   (upgrading to complete when every required group is ok);
5. cross-process races are bounded by the unique constraint: on
   IntegrityError retry the select-then-merge once, then fall back to
   returning the existing row idempotently.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from sqlalchemy import and_, asc, desc, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.storage import DatabaseManager, MarketSentimentSnapshot

# 一期默认必备组（§3.3）；payload 固化的 required_groups 优先于该默认值。
DEFAULT_REQUIRED_GROUPS: Tuple[str, ...] = (
    "breadth",
    "limit_up_pool",
    "broken_pool",
    "turnover",
    "promotion",
    "prev_feedback",
)

# metric_status 组名 -> payload 顶层 section 键（§3.2 payload 草案）。
METRIC_STATUS_TO_SECTION: Dict[str, str] = {
    "breadth": "breadth",
    "limit_up_pool": "limit_up",
    "broken_pool": "broken_limit",
    "turnover": "turnover",
    "promotion": "promotion",
    "prev_feedback": "yesterday_limit_feedback",
    "sector": "sector_strength",  # 增强组：不计入 completeness 分母
}

QUALITY_STATUS_COMPLETE = "complete"
QUALITY_STATUS_PARTIAL = "partial"

ACTION_INSERTED = "inserted"
ACTION_REPLACED = "replaced"
ACTION_MERGED = "merged"
ACTION_SUPERSEDED = "superseded_by_existing_complete"
ACTION_IDEMPOTENT_RETURN = "idempotent_return"


@dataclass(frozen=True)
class SnapshotSaveResult:
    """Outcome of ``save_snapshot``.

    ``action`` is one of ``inserted`` / ``replaced`` / ``merged`` /
    ``superseded_by_existing_complete`` / ``idempotent_return``.
    """

    snapshot: MarketSentimentSnapshot
    action: str
    superseded_by_existing_complete: bool


def _dumps(data: Any) -> str:
    """Serialize via the storage-layer safe JSON helper (never raises)."""
    return DatabaseManager._safe_json_dumps(data)


def _loads_object(text: Optional[str]) -> Dict[str, Any]:
    try:
        value = json.loads(text) if text else {}
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _loads_array(text: Optional[str]) -> List[Any]:
    try:
        value = json.loads(text) if text else []
    except (TypeError, ValueError):
        return []
    return value if isinstance(value, list) else []


def derive_snapshot_status(payload: Optional[Dict[str, Any]]) -> Tuple[str, float]:
    """Derive (quality_status, completeness) from a payload (§3.3).

    completeness = ok 必备组数 / 必备组总数（组粒度；required_groups 取
    payload 固化值，缺省回退 DEFAULT_REQUIRED_GROUPS；增强组不计入）。
    """
    payload = payload or {}
    metric_status = payload.get("metric_status") or {}
    required = payload.get("required_groups") or list(DEFAULT_REQUIRED_GROUPS)
    required = [group for group in required if isinstance(group, str)]
    if not required or not metric_status:
        return QUALITY_STATUS_PARTIAL, 0.0
    ok_count = sum(1 for group in required if metric_status.get(group) == "ok")
    completeness = round(ok_count / len(required), 6)
    status = QUALITY_STATUS_COMPLETE if ok_count == len(required) else QUALITY_STATUS_PARTIAL
    return status, completeness


def _merge_partial_payloads(
    old_payload: Dict[str, Any], new_payload: Dict[str, Any]
) -> Tuple[Dict[str, Any], Set[str]]:
    """Group-level fill-in merge of two partial payloads (§3.4 rule 4).

    Returns the merged payload plus the set of metric groups whose data was
    taken from the new payload (used to merge provider traces consistently).
    """
    old_status = dict(old_payload.get("metric_status") or {})
    new_status = dict(new_payload.get("metric_status") or {})
    merged = dict(old_payload)
    groups_from_new: Set[str] = set()
    merged_status: Dict[str, Any] = {}

    for group, section in METRIC_STATUS_TO_SECTION.items():
        old_ok = old_status.get(group) == "ok"
        new_ok = new_status.get(group) == "ok"
        if old_ok:
            # 旧组 ok → 保留旧值（先到先得，防部分数据漂移）
            merged_status[group] = "ok"
        elif new_ok:
            # 旧组非 ok 且新组 ok → 用新组数据填充
            merged[section] = new_payload.get(section)
            merged_status[group] = "ok"
            groups_from_new.add(group)
        elif section in old_payload or group in old_status:
            # 双方均非 ok → 保留旧组；仅当旧 section 缺失时补新值
            merged_status[group] = old_status.get(group)
            merged.setdefault(section, new_payload.get(section))
        elif section in new_payload or group in new_status:
            # 旧组完全没有 → 视作填空，数据与 trace 均来自新
            if section in new_payload:
                merged[section] = new_payload[section]
            merged_status[group] = new_status.get(group)
            if group in new_status:
                groups_from_new.add(group)

    # 未知/未来组的 metric_status 键：旧值优先，缺失补新值
    for group, status in old_status.items():
        merged_status.setdefault(group, status)
    for group, status in new_status.items():
        merged_status.setdefault(group, status)
    merged["metric_status"] = merged_status

    # 顶层标量字段填空（prev_trade_date/narrative/required_groups/未来字段）：
    # 旧值为空或缺失时用新值补，非空则保留旧值
    group_sections = set(METRIC_STATUS_TO_SECTION.values())
    for key, value in new_payload.items():
        if key == "metric_status" or key in group_sections:
            continue
        if merged.get(key) is None:
            merged[key] = value

    return merged, groups_from_new


def _merge_provider_traces(
    old_trace: List[Any], new_trace: List[Any], groups_from_new: Set[str]
) -> List[Any]:
    """Keep old trace entries except for groups taken from the new payload,
    whose new entries are appended in their original order."""
    merged: List[Any] = []
    for entry in old_trace or []:
        if isinstance(entry, dict) and entry.get("metric_group") in groups_from_new:
            continue
        merged.append(entry)
    for entry in new_trace or []:
        if isinstance(entry, dict) and entry.get("metric_group") in groups_from_new:
            merged.append(entry)
    return merged


class MarketSentimentRepository:
    """DB access layer for ``market_sentiment_snapshots`` (issue #1939)."""

    def __init__(self, db_manager: Optional[DatabaseManager] = None):
        self.db = db_manager or DatabaseManager.get_instance()

    # --- save: §3.4 rules ---------------------------------------------------

    def save_snapshot(
        self,
        payload: Dict[str, Any],
        provider_trace: Optional[Sequence[Dict[str, Any]]] = None,
        *,
        market: Optional[str] = None,
        trade_date: Optional[str] = None,
    ) -> SnapshotSaveResult:
        """Persist one snapshot for (market, trade_date) with §3.4 merge rules."""
        if not isinstance(payload, dict):
            raise ValueError("payload must be a dict")
        normalized_payload = dict(payload)
        resolved_market = market or normalized_payload.get("market") or "cn"
        resolved_trade_date = trade_date or normalized_payload.get("trade_date")
        if not resolved_trade_date:
            raise ValueError("trade_date is required (payload['trade_date'] or keyword)")
        normalized_trace = list(provider_trace or [])

        new_status, new_completeness = derive_snapshot_status(normalized_payload)
        payload_json = _dumps(normalized_payload)
        trace_json = _dumps(normalized_trace)

        last_error: Optional[IntegrityError] = None
        for _attempt in range(2):
            try:
                return self._attempt_save(
                    resolved_market,
                    resolved_trade_date,
                    payload_json,
                    trace_json,
                    new_status,
                    new_completeness,
                )
            except IntegrityError as exc:
                # 规则5：跨进程竞态撞唯一约束 → 重试一次 select-then-merge
                last_error = exc

        # 仍失败 → 读取既有行幂等返回
        with self.db.get_session() as session:
            existing = self._load_existing(session, resolved_market, resolved_trade_date)
            if existing is None:
                raise last_error  # pragma: no cover - defensive, race with DELETE
            session.refresh(existing)
            superseded = (
                existing.quality_status == QUALITY_STATUS_COMPLETE
                and new_status == QUALITY_STATUS_PARTIAL
            )
            return SnapshotSaveResult(
                snapshot=existing,
                action=ACTION_IDEMPOTENT_RETURN,
                superseded_by_existing_complete=superseded,
            )

    def _attempt_save(
        self,
        market: str,
        trade_date: str,
        payload_json: str,
        trace_json: str,
        new_status: str,
        new_completeness: float,
    ) -> SnapshotSaveResult:
        with self.db.get_session() as session:
            existing = self._load_existing(session, market, trade_date)

            # 规则1：无既有行 → 直接 insert（partial 或 complete 均允许）
            if existing is None:
                row = MarketSentimentSnapshot(
                    market=market,
                    trade_date=trade_date,
                    quality_status=new_status,
                    completeness=new_completeness,
                    payload=payload_json,
                    provider_trace=trace_json,
                )
                self._insert_snapshot(session, row)
                session.commit()
                session.refresh(row)
                return SnapshotSaveResult(
                    snapshot=row,
                    action=ACTION_INSERTED,
                    superseded_by_existing_complete=False,
                )

            # 规则2：incoming complete → 整体替换（允许同日重算修正）
            if new_status == QUALITY_STATUS_COMPLETE:
                existing.payload = payload_json
                existing.provider_trace = trace_json
                existing.quality_status = new_status
                existing.completeness = new_completeness
                existing.updated_at = datetime.now()
                session.commit()
                session.refresh(existing)
                return SnapshotSaveResult(
                    snapshot=existing,
                    action=ACTION_REPLACED,
                    superseded_by_existing_complete=False,
                )

            # 规则3：partial 不覆盖 complete（行级比较，不动 updated_at）
            if existing.quality_status == QUALITY_STATUS_COMPLETE:
                session.refresh(existing)
                return SnapshotSaveResult(
                    snapshot=existing,
                    action=ACTION_SUPERSEDED,
                    superseded_by_existing_complete=True,
                )

            # 规则4：partial + partial → 组级填空合并后重算状态
            old_payload = _loads_object(existing.payload)
            old_trace = _loads_array(existing.provider_trace)
            new_payload = _loads_object(payload_json)
            new_trace = _loads_array(trace_json)
            merged_payload, groups_from_new = _merge_partial_payloads(old_payload, new_payload)
            merged_trace = _merge_provider_traces(old_trace, new_trace, groups_from_new)
            merged_status, merged_completeness = derive_snapshot_status(merged_payload)
            changed = (
                merged_payload != old_payload
                or merged_trace != old_trace
                or merged_status != existing.quality_status
                or merged_completeness != existing.completeness
            )
            if changed:
                existing.payload = _dumps(merged_payload)
                existing.provider_trace = _dumps(merged_trace)
                existing.quality_status = merged_status
                existing.completeness = merged_completeness
                existing.updated_at = datetime.now()
                session.commit()
                session.refresh(existing)
            return SnapshotSaveResult(
                snapshot=existing,
                action=ACTION_MERGED,
                superseded_by_existing_complete=False,
            )

    # --- seams (monkeypatch points for race-condition tests) ----------------

    def _load_existing(
        self, session: Session, market: str, trade_date: str
    ) -> Optional[MarketSentimentSnapshot]:
        return session.execute(
            select(MarketSentimentSnapshot)
            .where(
                MarketSentimentSnapshot.market == market,
                MarketSentimentSnapshot.trade_date == trade_date,
            )
            .limit(1)
        ).scalar_one_or_none()

    def _insert_snapshot(self, session: Session, row: MarketSentimentSnapshot) -> None:
        session.add(row)
        session.flush()

    # --- queries --------------------------------------------------------------

    def get_by_market_date(
        self, market: str = "cn", trade_date: Optional[str] = None
    ) -> Optional[MarketSentimentSnapshot]:
        if not trade_date:
            raise ValueError("trade_date is required")
        with self.db.get_session() as session:
            row = self._load_existing(session, market, trade_date)
            if row is None:
                return None
            session.refresh(row)
            return row

    def list_snapshots(
        self,
        market: str = "cn",
        *,
        limit: int = 30,
        offset: int = 0,
        order: str = "desc",
    ) -> Tuple[List[MarketSentimentSnapshot], int]:
        """Paginated snapshot index ordered by trade_date (§4.2).

        Validation of API bounds (limit 1~200, offset >= 0) belongs to the
        API layer; the repository clamps defensively.
        """
        if order not in ("asc", "desc"):
            raise ValueError(f"order must be 'asc' or 'desc', got: {order!r}")
        safe_limit = max(1, int(limit))
        safe_offset = max(0, int(offset))
        date_col = MarketSentimentSnapshot.trade_date
        id_col = MarketSentimentSnapshot.id
        direction = desc if order == "desc" else asc
        with self.db.get_session() as session:
            total = (
                session.execute(
                    select(func.count(MarketSentimentSnapshot.id)).where(
                        MarketSentimentSnapshot.market == market
                    )
                ).scalar()
                or 0
            )
            rows = (
                session.execute(
                    select(MarketSentimentSnapshot)
                    .where(MarketSentimentSnapshot.market == market)
                    .order_by(direction(date_col), direction(id_col))
                    .offset(safe_offset)
                    .limit(safe_limit)
                )
                .scalars()
                .all()
            )
            return list(rows), int(total)

    def query_trend_range(
        self,
        market: str = "cn",
        *,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        strict_before: Optional[str] = None,
    ) -> List[MarketSentimentSnapshot]:
        """Trade-date range query with dual boundary semantics (§4.4).

        Default/inclusive mode: ``trade_date >= start_date AND
        trade_date <= end_date``. Strict mode (percentile reservation):
        ``trade_date < strict_before`` excludes the target day itself and
        takes precedence over ``end_date``. Results are ordered by
        trade_date ascending; missing days stay missing (no interpolation).
        """
        conditions = [MarketSentimentSnapshot.market == market]
        if start_date:
            conditions.append(MarketSentimentSnapshot.trade_date >= start_date)
        if strict_before is not None:
            conditions.append(MarketSentimentSnapshot.trade_date < strict_before)
        elif end_date is not None:
            conditions.append(MarketSentimentSnapshot.trade_date <= end_date)
        with self.db.get_session() as session:
            rows = (
                session.execute(
                    select(MarketSentimentSnapshot)
                    .where(and_(*conditions))
                    .order_by(asc(MarketSentimentSnapshot.trade_date))
                )
                .scalars()
                .all()
            )
            return list(rows)
