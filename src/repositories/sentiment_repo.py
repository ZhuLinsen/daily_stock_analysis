"""Database access for immutable, date-keyed sentiment snapshots."""

from __future__ import annotations

from datetime import date
import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.storage import SentimentSnapshot


class SentimentSnapshotConflict(ValueError):
    """An existing snapshot has different data or a different rule version."""


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class SentimentRepository:
    def __init__(self, session: Session):
        self.session = session

    def get(self, market: str, trade_date: date) -> SentimentSnapshot | None:
        return self.session.execute(
            select(SentimentSnapshot).where(
                SentimentSnapshot.market == market,
                SentimentSnapshot.trade_date == trade_date,
            )
        ).scalar_one_or_none()

    def list(self, market: str, *, end_date: date | None = None,
             limit: int = 60) -> list[SentimentSnapshot]:
        statement = select(SentimentSnapshot).where(SentimentSnapshot.market == market)
        if end_date is not None:
            statement = statement.where(SentimentSnapshot.trade_date <= end_date)
        return list(self.session.execute(
            statement.order_by(SentimentSnapshot.trade_date.desc()).limit(limit)
        ).scalars())

    def save(self, snapshot: dict[str, Any]) -> tuple[str, SentimentSnapshot]:
        values = {
            "market": snapshot["market"],
            "trade_date": snapshot["trade_date"],
            "previous_trade_date": snapshot["previous_trade_date"],
            "definition_version": snapshot["definition_version"],
            "quality_status": snapshot["quality_status"],
            "metrics_json": _json(snapshot["metrics"]),
            "components_json": _json(snapshot["components"]),
            "provider_trace_json": _json(snapshot["provider_trace"]),
            "completeness_json": _json(snapshot["completeness"]),
        }
        existing = self.get(values["market"], values["trade_date"])
        if existing is not None:
            return self._compare_existing(existing, values)
        record = SentimentSnapshot(**values)
        self.session.add(record)
        try:
            self.session.commit()
        except IntegrityError:
            self.session.rollback()
            existing = self.get(values["market"], values["trade_date"])
            if existing is not None:
                return self._compare_existing(existing, values)
            raise
        self.session.refresh(record)
        return "inserted", record

    @staticmethod
    def _compare_existing(
        existing: SentimentSnapshot, values: dict[str, Any],
    ) -> tuple[str, SentimentSnapshot]:
        if all(getattr(existing, key) == value for key, value in values.items()):
            return "unchanged", existing
        raise SentimentSnapshotConflict(
            "snapshot already exists with different input or definition; explicit revision is required"
        )


def public_snapshot(record: SentimentSnapshot) -> dict[str, Any]:
    """Expose measures and provenance, while retaining licensed code lists locally."""
    components = json.loads(record.components_json)
    trace = json.loads(record.provider_trace_json)
    trace.pop("source_file", None)
    return {
        "market": record.market,
        "trade_date": record.trade_date,
        "previous_trade_date": record.previous_trade_date,
        "definition_version": record.definition_version,
        "quality_status": record.quality_status,
        "metrics": json.loads(record.metrics_json),
        "break_numerator": components["break_numerator"],
        "break_denominator": components["break_denominator"],
        "promotion_numerator": components["promotion_numerator"],
        "promotion_denominator": components["promotion_denominator"],
        "provider_trace": trace,
        "completeness": json.loads(record.completeness_json),
        "created_at": record.created_at,
    }
