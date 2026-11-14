"""Database access for immutable, date-keyed sentiment snapshots."""

from __future__ import annotations

from datetime import date
import json
import math
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

    def on_dates(self, market: str, dates: list[date]) -> dict[date, SentimentSnapshot]:
        records = self.session.scalars(select(SentimentSnapshot).where(
            SentimentSnapshot.market == market, SentimentSnapshot.trade_date.in_(dates),
        ))
        return {record.trade_date: record for record in records}

    def public(self, record: SentimentSnapshot) -> dict[str, Any]:
        result = public_snapshot(record)
        metrics = result["metrics"]
        amount = metrics.get("turnover_yuan")
        if (not isinstance(amount, (int, float)) or isinstance(amount, bool)
                or not math.isfinite(amount) or amount <= 0
                or record.quality_status == "imported" or record.previous_trade_date >= record.trade_date):
            return result
        prior = self.get(record.market, record.previous_trade_date)
        if prior is not None and prior.definition_version == record.definition_version and prior.quality_status != "imported":
            prior_amount = json.loads(prior.metrics_json).get("turnover_yuan")
            if (isinstance(prior_amount, (float, int)) and not isinstance(prior_amount, bool)
                    and math.isfinite(prior_amount) and prior_amount > 0):
                difference = amount - prior_amount
                ratio = difference / prior_amount
                if math.isfinite(ratio):
                    metrics.update(previous_turnover_yuan=prior_amount, turnover_change_yuan=difference,
                                   turnover_change_ratio=ratio)
        return result

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
        # A future-row update can repair the workbook's advertised dimension
        # without changing its historical inputs. Keep the original stored
        # provenance and still compare every semantic field and the digest.
        old_trace = json.loads(existing.provider_trace_json)
        new_trace = json.loads(values["provider_trace_json"])
        old_trace.pop("dimension_repaired", None)
        new_trace.pop("dimension_repaired", None)
        # An identical source result may be retrieved again at a later time.
        # Preserve the first capture time; changes to the input hash still conflict.
        old_trace.pop("retrieved_at", None)
        new_trace.pop("retrieved_at", None)
        if old_trace == new_trace and all(
            getattr(existing, key) == value
            for key, value in values.items() if key != "provider_trace_json"
        ):
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
        "eligible_quote_count": components.get("eligible_quote_count"),
        "limit_down_count": components.get("limit_down_count"),
        "advancing_count": components.get("advancing_count"),
        "provider_trace": trace,
        "completeness": json.loads(record.completeness_json),
        "created_at": record.created_at,
    }
