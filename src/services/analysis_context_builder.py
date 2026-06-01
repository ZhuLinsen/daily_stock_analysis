# -*- coding: utf-8 -*-
"""Assembler for the internal AnalysisContextPack P2 contract."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence

from src.schemas.analysis_context_pack import (
    AnalysisContextBlock,
    AnalysisContextItem,
    AnalysisContextPack,
    AnalysisSubject,
    ContextFieldStatus,
    DataQuality,
)


_REALTIME_OVERLAY_WARNING = "intraday_realtime_overlay"
_REALTIME_FALLBACK_WARNING = "realtime_provider_fallback"
_FUNDAMENTAL_FAILED_REASON = "fundamental_pipeline_failed"
_QUALITY_BLOCK_WEIGHTS: Dict[str, int] = {
    "quote": 25,
    "daily_bars": 25,
    "technical": 25,
    "news": 10,
    "fundamentals": 10,
    "chip": 5,
}
_STATUS_SCORES: Dict[ContextFieldStatus, int] = {
    ContextFieldStatus.AVAILABLE: 100,
    ContextFieldStatus.PARTIAL: 75,
    ContextFieldStatus.ESTIMATED: 75,
    ContextFieldStatus.NOT_SUPPORTED: 70,
    ContextFieldStatus.FALLBACK: 65,
    ContextFieldStatus.STALE: 50,
    ContextFieldStatus.MISSING: 35,
    ContextFieldStatus.FETCH_FAILED: 25,
}
_CORE_LIMITATION_STATUSES = {
    ContextFieldStatus.STALE,
    ContextFieldStatus.FALLBACK,
    ContextFieldStatus.MISSING,
    ContextFieldStatus.FETCH_FAILED,
    ContextFieldStatus.PARTIAL,
    ContextFieldStatus.ESTIMATED,
}
_AUX_LIMITATION_STATUSES = {
    ContextFieldStatus.FETCH_FAILED,
    ContextFieldStatus.FALLBACK,
    ContextFieldStatus.STALE,
}


@dataclass(frozen=True)
class PipelineAnalysisArtifacts:
    """Artifacts already fetched by the stock analysis pipeline."""

    code: str
    stock_name: str
    market: str
    phase: Optional[Dict[str, Any]]
    base_context: Dict[str, Any]
    enhanced_context: Dict[str, Any]
    realtime_quote: Optional[Any]
    trend_result: Optional[Any]
    chip_data: Optional[Any]
    fundamental_context: Optional[Dict[str, Any]]
    news_context: Optional[str]
    news_result_count: Optional[int]
    metadata: Dict[str, Any]


class AnalysisContextBuilder:
    """Build AnalysisContextPack from existing pipeline artifacts only."""

    @staticmethod
    def build(artifacts: PipelineAnalysisArtifacts) -> AnalysisContextPack:
        metadata = dict(artifacts.metadata or {})
        if artifacts.news_result_count is not None:
            metadata["news_result_count"] = artifacts.news_result_count

        blocks: Dict[str, AnalysisContextBlock] = {}
        data_quality_warnings: List[str] = []

        blocks["quote"] = _build_quote_block(artifacts)
        blocks["daily_bars"] = _build_daily_bars_block(artifacts)
        technical_block, technical_warnings = _build_technical_block(artifacts)
        blocks["technical"] = technical_block
        data_quality_warnings.extend(technical_warnings)
        blocks["chip"] = _build_chip_block(artifacts)
        blocks["fundamentals"] = _build_fundamentals_block(artifacts)
        blocks["news"] = _build_news_block(artifacts)
        data_quality = _build_data_quality(blocks, warnings=data_quality_warnings)

        return AnalysisContextPack(
            subject=AnalysisSubject(
                code=artifacts.code,
                stock_name=artifacts.stock_name or None,
                market=artifacts.market or None,
            ),
            phase=artifacts.phase,
            blocks=blocks,
            data_quality=data_quality,
            metadata=metadata,
        )

    @staticmethod
    def build_batch(items: Sequence[PipelineAnalysisArtifacts]) -> List[AnalysisContextPack]:
        return [AnalysisContextBuilder.build(item) for item in items]


def _build_quote_block(artifacts: PipelineAnalysisArtifacts) -> AnalysisContextBlock:
    quote = _to_dict(artifacts.realtime_quote)
    if not quote:
        return AnalysisContextBlock(
            status=ContextFieldStatus.MISSING,
            items={
                "quote": AnalysisContextItem(
                    status=ContextFieldStatus.MISSING,
                    missing_reason="realtime_quote_missing",
                )
            },
        )

    source = _source_text(quote.get("source"))
    status = ContextFieldStatus.AVAILABLE
    warnings: List[str] = []
    fallback_from = _metadata_value(
        quote,
        "fallback_from",
        "quote_fallback_from",
        "realtime_fallback_from",
        "fallback_provider",
    ) or _metadata_value(
        artifacts.metadata,
        "quote_fallback_from",
        "realtime_fallback_from",
        "fallback_from",
    )
    timestamp = _quote_timestamp(artifacts, quote)
    is_fallback = fallback_from is not None or source == "fallback"

    if _has_explicit_quote_stale_marker(artifacts, quote):
        status = ContextFieldStatus.STALE
        warnings.append("quote_stale")
    elif is_fallback:
        status = ContextFieldStatus.FALLBACK
        if fallback_from is None:
            warnings.append(_REALTIME_FALLBACK_WARNING)

    items = {
        key: AnalysisContextItem(
            status=status,
            value=value,
            source=source,
            timestamp=timestamp,
            fallback_from=fallback_from if is_fallback else None,
            warnings=list(warnings),
        )
        for key, value in quote.items()
        if value is not None
    }
    return AnalysisContextBlock(
        status=status,
        items=items,
        source=source,
        timestamp=timestamp,
        warnings=warnings,
        metadata=_quote_metadata(artifacts, quote),
    )


def _build_daily_bars_block(artifacts: PipelineAnalysisArtifacts) -> AnalysisContextBlock:
    context = artifacts.base_context or {}
    date_value = context.get("date")
    metadata = {
        key: value
        for key, value in {
            "date": date_value,
            "data_missing": bool(context.get("data_missing")),
        }.items()
        if value not in (None, "")
    }
    if context.get("data_missing"):
        return AnalysisContextBlock(
            status=ContextFieldStatus.MISSING,
            items={
                "today": AnalysisContextItem(
                    status=ContextFieldStatus.MISSING,
                    value=context.get("today") or None,
                    missing_reason="daily_bars_missing",
                    metadata={"date": date_value} if date_value else {},
                ),
                "yesterday": AnalysisContextItem(
                    status=ContextFieldStatus.MISSING,
                    value=context.get("yesterday") or None,
                    missing_reason="daily_bars_missing",
                ),
            },
            source="storage.get_analysis_context",
            metadata=metadata,
        )

    items: Dict[str, AnalysisContextItem] = {}
    for key in ("today", "yesterday"):
        value = context.get(key)
        items[key] = AnalysisContextItem(
            status=ContextFieldStatus.AVAILABLE if value else ContextFieldStatus.MISSING,
            value=value or None,
            source="storage.get_analysis_context",
            missing_reason=None if value else f"{key}_missing",
        )
    if date_value:
        items["date"] = AnalysisContextItem(
            status=ContextFieldStatus.AVAILABLE,
            value=date_value,
            source="storage.get_analysis_context",
            metadata={"date": date_value},
        )

    bar_statuses = [items[key].status for key in ("today", "yesterday")]
    if all(status == ContextFieldStatus.AVAILABLE for status in bar_statuses):
        block_status = ContextFieldStatus.AVAILABLE
    elif any(status == ContextFieldStatus.AVAILABLE for status in bar_statuses):
        block_status = ContextFieldStatus.PARTIAL
    else:
        block_status = ContextFieldStatus.MISSING
    return AnalysisContextBlock(
        status=block_status,
        items=items,
        source="storage.get_analysis_context",
        metadata=metadata,
    )


def _build_technical_block(
    artifacts: PipelineAnalysisArtifacts,
) -> tuple[AnalysisContextBlock, List[str]]:
    trend = _to_dict(artifacts.trend_result)
    if not trend:
        return (
            AnalysisContextBlock(
                status=ContextFieldStatus.MISSING,
                items={
                    "trend_result": AnalysisContextItem(
                        status=ContextFieldStatus.MISSING,
                        missing_reason="trend_result_missing",
                    )
                },
            ),
            [],
        )

    explicit_intraday_overlay = _has_explicit_intraday_overlay(
        artifacts.enhanced_context
    )
    has_realtime_overlay = explicit_intraday_overlay or _has_realtime_overlay(
        artifacts.enhanced_context
    )
    warnings = [_REALTIME_OVERLAY_WARNING] if has_realtime_overlay else []
    block_status = (
        ContextFieldStatus.PARTIAL
        if has_realtime_overlay
        else ContextFieldStatus.AVAILABLE
    )
    items: Dict[str, AnalysisContextItem] = {
        "trend_result": AnalysisContextItem(
            status=ContextFieldStatus.AVAILABLE,
            value=trend,
            warnings=list(warnings),
        )
    }
    if has_realtime_overlay:
        items["intraday_overlay"] = AnalysisContextItem(
            status=ContextFieldStatus.ESTIMATED,
            value=(artifacts.enhanced_context or {}).get("today"),
            warnings=list(warnings),
        )

    return (
        AnalysisContextBlock(
            status=block_status,
            items=items,
            warnings=warnings,
            metadata={
                key: value
                for key, value in {
                    "overlay_source": _realtime_overlay_source(
                        artifacts.enhanced_context
                    ),
                    "is_partial_bar": _today_metadata_value(
                        artifacts.enhanced_context, "is_partial_bar", "isPartialBar"
                    ),
                    "is_estimated": _today_metadata_value(
                        artifacts.enhanced_context, "is_estimated", "isEstimated"
                    ),
                    "estimated_fields": _today_metadata_value(
                        artifacts.enhanced_context,
                        "estimated_fields",
                        "estimatedFields",
                    ),
                }.items()
                if value is not None
            },
        ),
        warnings,
    )


def _build_chip_block(artifacts: PipelineAnalysisArtifacts) -> AnalysisContextBlock:
    chip = _to_dict(artifacts.chip_data)
    if not chip:
        not_supported = bool((artifacts.metadata or {}).get("chip_not_supported"))
        status = (
            ContextFieldStatus.NOT_SUPPORTED
            if not_supported
            else ContextFieldStatus.MISSING
        )
        return AnalysisContextBlock(
            status=status,
            items={
                "chip_distribution": AnalysisContextItem(
                    status=status,
                    missing_reason=(
                        "chip_not_supported"
                        if not_supported
                        else "chip_distribution_missing"
                    ),
                )
            },
        )

    source = _source_text(chip.get("source"))
    return AnalysisContextBlock(
        status=ContextFieldStatus.AVAILABLE,
        items={
            key: AnalysisContextItem(
                status=ContextFieldStatus.AVAILABLE,
                value=value,
                source=source,
            )
            for key, value in chip.items()
            if value is not None
        },
        source=source,
        metadata={"date": chip.get("date")} if chip.get("date") else {},
    )


def _build_fundamentals_block(artifacts: PipelineAnalysisArtifacts) -> AnalysisContextBlock:
    context = artifacts.fundamental_context if isinstance(artifacts.fundamental_context, dict) else None
    if not context:
        return AnalysisContextBlock(
            status=ContextFieldStatus.MISSING,
            items={
                "fundamental_context": AnalysisContextItem(
                    status=ContextFieldStatus.MISSING,
                    missing_reason="fundamental_context_missing",
                )
            },
        )

    raw_status = str(context.get("status") or "").strip().lower()
    status = _fundamental_status(raw_status)
    missing_reason = (
        _FUNDAMENTAL_FAILED_REASON
        if raw_status == "failed"
        else ("fundamentals_not_supported" if raw_status == "not_supported" else None)
    )
    coverage = context.get("coverage") if isinstance(context.get("coverage"), dict) else {}
    source_chain = context.get("source_chain") if isinstance(context.get("source_chain"), list) else []
    source = _source_from_chain(source_chain)
    metadata = {
        "status": raw_status or None,
        "coverage": coverage,
        "source_chain": source_chain,
    }
    metadata = {key: value for key, value in metadata.items() if value not in (None, {}, [])}

    return AnalysisContextBlock(
        status=status,
        items={
            "status": AnalysisContextItem(
                status=status,
                value=raw_status or None,
                source=source,
                missing_reason=missing_reason,
            ),
            "coverage": AnalysisContextItem(
                status=_fundamental_payload_status(status, bool(coverage)),
                value=coverage or None,
                source=source,
                missing_reason=_fundamental_payload_missing_reason(
                    raw_status,
                    bool(coverage),
                    "fundamental_coverage_missing",
                ),
            ),
            "source_chain": AnalysisContextItem(
                status=_fundamental_payload_status(status, bool(source_chain)),
                value=source_chain or None,
                source=source,
                missing_reason=_fundamental_payload_missing_reason(
                    raw_status,
                    bool(source_chain),
                    "fundamental_source_chain_missing",
                ),
            ),
        },
        source=source,
        metadata=metadata,
    )


def _build_news_block(artifacts: PipelineAnalysisArtifacts) -> AnalysisContextBlock:
    content = (artifacts.news_context or "").strip()
    metadata: Dict[str, Any] = {}
    if artifacts.news_result_count is not None:
        metadata["news_result_count"] = artifacts.news_result_count

    if not content:
        return AnalysisContextBlock(
            status=ContextFieldStatus.MISSING,
            items={
                "content": AnalysisContextItem(
                    status=ContextFieldStatus.MISSING,
                    missing_reason="news_context_missing",
                )
            },
            metadata=metadata,
        )

    return AnalysisContextBlock(
        status=ContextFieldStatus.AVAILABLE,
        items={
            "content": AnalysisContextItem(
                status=ContextFieldStatus.AVAILABLE,
                value=content,
            )
        },
        metadata=metadata,
    )


def _build_data_quality(
    blocks: Dict[str, AnalysisContextBlock],
    *,
    warnings: List[str],
) -> DataQuality:
    block_scores: Dict[str, int] = {}
    weighted_sum = 0
    for key, weight in _QUALITY_BLOCK_WEIGHTS.items():
        status = _quality_block_status(blocks, key)
        score = _STATUS_SCORES.get(status, _STATUS_SCORES[ContextFieldStatus.MISSING])
        block_scores[key] = score
        weighted_sum += score * weight

    overall_score = int(round(weighted_sum / 100))
    return DataQuality(
        overall_score=overall_score,
        level=_quality_level(overall_score),
        block_scores=block_scores,
        limitations=_quality_limitations(blocks),
        warnings=warnings,
    )


def _quality_block_status(
    blocks: Dict[str, AnalysisContextBlock],
    key: str,
) -> ContextFieldStatus:
    block = blocks.get(key)
    if block is None:
        return ContextFieldStatus.MISSING
    status = block.status
    if isinstance(status, ContextFieldStatus):
        return status
    try:
        return ContextFieldStatus(str(status))
    except ValueError:
        return ContextFieldStatus.MISSING


def _quality_level(score: int) -> str:
    if score >= 85:
        return "good"
    if score >= 70:
        return "usable"
    if score >= 55:
        return "limited"
    return "poor"


def _quality_limitations(blocks: Dict[str, AnalysisContextBlock]) -> List[str]:
    limitations: List[str] = []
    for key in ("quote", "daily_bars", "technical"):
        status = _quality_block_status(blocks, key)
        if status in _CORE_LIMITATION_STATUSES:
            limitations.append(f"{key}: {status.value}")

    for key in ("news", "fundamentals", "chip"):
        status = _quality_block_status(blocks, key)
        if status in _AUX_LIMITATION_STATUSES:
            limitations.append(f"{key}: {status.value}")

    return limitations[:5]


def _to_dict(value: Optional[Any]) -> Dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, Mapping):
        return dict(value)
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        result = to_dict()
        if not isinstance(result, Mapping):
            raise TypeError(
                f"{type(value).__name__}.to_dict() must return a mapping"
            )
        return dict(result)
    value_dict = getattr(value, "__dict__", None)
    if isinstance(value_dict, dict):
        return dict(value_dict)
    return {}


def _source_text(value: Any) -> Optional[str]:
    if value is None:
        return None
    enum_value = getattr(value, "value", None)
    if enum_value is not None:
        value = enum_value
    text = str(value).strip()
    return text or None


def _metadata_value(metadata: Dict[str, Any], *keys: str) -> Optional[str]:
    for key in keys:
        value = (metadata or {}).get(key)
        if value not in (None, ""):
            return str(value)
    return None


def _metadata_iso_datetime_value(metadata: Dict[str, Any], *keys: str) -> Optional[str]:
    for key in keys:
        value = (metadata or {}).get(key)
        if value in (None, ""):
            continue
        if isinstance(value, datetime):
            return value.isoformat()
        text = str(value).strip()
        if not text:
            continue
        if "T" not in text:
            continue
        normalized = text[:-1] + "+00:00" if text.endswith("Z") else text
        try:
            datetime.fromisoformat(normalized)
        except ValueError:
            continue
        return text
    return None


def _quote_timestamp(
    artifacts: PipelineAnalysisArtifacts,
    quote: Dict[str, Any],
) -> Optional[str]:
    return _metadata_iso_datetime_value(
        quote,
        "provider_timestamp",
        "quote_timestamp",
    ) or _metadata_iso_datetime_value(
        artifacts.metadata,
        "provider_timestamp",
        "quote_timestamp",
        "realtime_provider_timestamp",
    ) or _metadata_iso_datetime_value(
        quote,
        "fetched_at",
        "realtime_fetched_at",
    ) or _metadata_iso_datetime_value(
        artifacts.metadata,
        "fetched_at",
        "realtime_fetched_at",
    )


def _has_explicit_quote_stale_marker(
    artifacts: PipelineAnalysisArtifacts,
    quote: Dict[str, Any],
) -> bool:
    metadata = artifacts.metadata or {}
    for key in ("price_stale", "quote_stale", "is_stale"):
        if bool(metadata.get(key)) or bool(quote.get(key)):
            return True
    if bool(metadata.get("quote_stale_seconds")) or bool(
        quote.get("quote_stale_seconds")
    ):
        return True
    return False


def _quote_metadata(
    artifacts: PipelineAnalysisArtifacts,
    quote: Dict[str, Any],
) -> Dict[str, Any]:
    metadata: Dict[str, Any] = {}
    for key in (
        "price_stale",
        "quote_stale",
        "quote_stale_seconds",
        "is_stale",
        "stale_seconds",
        "fetched_at",
        "provider_timestamp",
        "fallback_from",
    ):
        if key in {"fetched_at", "provider_timestamp"}:
            value = _metadata_iso_datetime_value(artifacts.metadata or {}, key)
            if value is None:
                value = _metadata_iso_datetime_value(quote, key)
        else:
            value = (artifacts.metadata or {}).get(key)
            if value is None:
                value = quote.get(key)
        if value is not None:
            metadata[key] = value
    return metadata


def _today_dict(enhanced_context: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    today = (enhanced_context or {}).get("today")
    return today if isinstance(today, dict) else None


def _today_metadata_value(enhanced_context: Dict[str, Any], *keys: str) -> Any:
    today = _today_dict(enhanced_context)
    if today is None:
        return None
    for key in keys:
        value = today.get(key)
        if value is not None:
            return value
    return None


def _has_explicit_intraday_overlay(enhanced_context: Dict[str, Any]) -> bool:
    today = _today_dict(enhanced_context)
    if today is None:
        return False
    if bool(today.get("is_partial_bar")) or bool(today.get("isPartialBar")):
        return True
    if bool(today.get("is_estimated")) or bool(today.get("isEstimated")):
        return True
    estimated_fields = today.get("estimated_fields") or today.get("estimatedFields")
    return bool(estimated_fields)


def _has_realtime_overlay(enhanced_context: Dict[str, Any]) -> bool:
    today = _today_dict(enhanced_context)
    if today is None:
        return False
    data_source = today.get("data_source") or today.get("dataSource")
    return isinstance(data_source, str) and data_source.startswith("realtime:")


def _realtime_overlay_source(enhanced_context: Dict[str, Any]) -> Optional[str]:
    today = _today_dict(enhanced_context)
    if today is None:
        return None
    value = today.get("data_source") or today.get("dataSource")
    return value if isinstance(value, str) and value else None


def _fundamental_status(status: str) -> ContextFieldStatus:
    if status in {"ok", "available"}:
        return ContextFieldStatus.AVAILABLE
    if status == "not_supported":
        return ContextFieldStatus.NOT_SUPPORTED
    if status == "partial":
        return ContextFieldStatus.PARTIAL
    if status == "failed":
        return ContextFieldStatus.FETCH_FAILED
    return ContextFieldStatus.MISSING


def _fundamental_payload_status(
    block_status: ContextFieldStatus,
    has_payload: bool,
) -> ContextFieldStatus:
    if has_payload:
        return block_status
    if block_status in {
        ContextFieldStatus.NOT_SUPPORTED,
        ContextFieldStatus.FETCH_FAILED,
    }:
        return block_status
    return ContextFieldStatus.MISSING


def _fundamental_payload_missing_reason(
    raw_status: str,
    has_payload: bool,
    missing_reason: str,
) -> Optional[str]:
    if raw_status == "failed":
        return _FUNDAMENTAL_FAILED_REASON
    if raw_status == "not_supported":
        return "fundamentals_not_supported"
    if has_payload:
        return None
    return missing_reason


def _source_from_chain(source_chain: Any) -> Optional[str]:
    if not isinstance(source_chain, list) or not source_chain:
        return None
    first = source_chain[0]
    if isinstance(first, dict):
        return _source_text(first.get("provider") or first.get("source"))
    return _source_text(first)
