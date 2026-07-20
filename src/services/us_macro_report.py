"""Orchestration and deterministic Markdown rendering for the US macro MVP."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import logging
from typing import Any
import json

from src.providers.macro.fred import FREDProvider, US_FRED_SERIES
from src.schemas.macro import MacroObservation, USMacroAIExplanation, USMacroSnapshot
from src.services.us_macro_market_data import US_MACRO_MARKETS, USMacroMarketDataService
from src.services.us_macro_rules import assess_us_macro

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class USMacroReport:
    snapshot: USMacroSnapshot
    assessment: dict[str, Any]
    markdown: str
    ai_explanation: USMacroAIExplanation | None = None
    ai_warning: str | None = None


class USMacroReportService:
    """Collect independent sources without allowing one source to block the report."""

    def __init__(
        self,
        *,
        fred_api_key: str | None = None,
        fred_provider: FREDProvider | None = None,
        market_service: USMacroMarketDataService | None = None,
    ) -> None:
        self.fred_provider = fred_provider or (FREDProvider(fred_api_key) if fred_api_key else None)
        self.market_service = market_service or USMacroMarketDataService()

    def build_report(self) -> USMacroReport:
        observations, missing_indicators, warnings = self._fetch_observations()
        try:
            market_data, missing_markets = self.market_service.fetch()
        except Exception as exc:
            logger.warning("美国宏观市场快照获取失败: %s", exc)
            market_data, missing_markets = [], list(US_MACRO_MARKETS)
            warnings.append("市场快照获取失败，已降级为仅利率报告")
        if missing_markets:
            warnings.append("缺少市场数据：" + "、".join(missing_markets))

        snapshot = USMacroSnapshot(
            as_of=datetime.now(timezone.utc),
            observations=observations,
            market_data=market_data,
            missing_indicators=missing_indicators,
            warnings=warnings,
        )
        assessment = assess_us_macro(
            [item for item in market_data],
            [item.model_dump() for item in observations],
        )
        return USMacroReport(snapshot=snapshot, assessment=assessment, markdown=render_us_macro_markdown(snapshot, assessment))

    def add_ai_explanation(self, report: USMacroReport, analyzer: Any) -> USMacroReport:
        """Add validated prose only; deterministic data is never accepted from the model."""
        payload = {
            "observations": [item.model_dump(mode="json") for item in report.snapshot.observations],
            "missing_indicators": report.snapshot.missing_indicators,
            "warnings": report.snapshot.warnings,
            "assessment": report.assessment,
        }
        prompt = (
            "你是宏观报告解释助手。只能基于以下 JSON 写解释，不能改写或新增任何数值、"
            "方向、置信度、行情、新闻或政策事实；不得给出买卖点、仓位、收益保证或概率。"
            "市场价格数据不可用时，不得推测或补全市场价格。仅返回 JSON，字段为 core_logic,"
            "bullish_factors, bearish_factors, sector_impacts, risks, invalidation_conditions；"
            "所有列表字段均为字符串数组。\n" + json.dumps(payload, ensure_ascii=False)
        )
        try:
            raw = analyzer.generate_text(prompt, max_tokens=900, temperature=0.1)
            if not raw:
                raise ValueError("empty AI explanation")
            explanation = USMacroAIExplanation.model_validate_json(raw)
        except Exception as exc:
            logger.warning("美国宏观 AI 解释不可用: error_type=%s", type(exc).__name__)
            return USMacroReport(report.snapshot, report.assessment, report.markdown, ai_warning="AI解释暂不可用")
        markdown = report.markdown + render_ai_explanation(explanation)
        return USMacroReport(report.snapshot, report.assessment, markdown, explanation)

    def _fetch_observations(self) -> tuple[list[MacroObservation], list[str], list[str]]:
        if self.fred_provider is None:
            return [], list(US_FRED_SERIES), ["未配置 FRED_API_KEY，利率数据未获取"]

        observations: list[MacroObservation] = []
        missing: list[str] = []
        warnings: list[str] = []
        for indicator, series_id in US_FRED_SERIES.items():
            try:
                observation = self.fred_provider.fetch_latest(indicator, series_id)
            except Exception as exc:
                logger.warning(
                    "FRED 指标获取失败: indicator=%s series=%s error_type=%s",
                    indicator,
                    series_id,
                    type(exc).__name__,
                )
                missing.append(indicator)
                continue
            if observation is None or observation.value is None:
                missing.append(indicator)
            else:
                observations.append(observation)
        return observations, missing, warnings


def render_us_macro_markdown(snapshot: USMacroSnapshot, assessment: dict[str, Any]) -> str:
    """Render a data-only report; this path never produces investment advice."""
    horizon = assessment["horizons"]["未来1周"]
    lines = [
        "# 🇺🇸 美国宏观基础报告",
        "",
        f"> 生成时间：{snapshot.as_of.astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}；数据可能延迟，非投资建议。",
        "",
        "## 核心结论",
        f"- 规则状态：`{assessment['regime']}`",
        *[
            f"- {name}：{value['direction']}（置信度：{value['confidence']}，规则分：{value['score']}）"
            for name, value in assessment["horizons"].items()
        ],
    ]
    if assessment.get("warning"):
        lines.append(f"- 降级说明：{assessment['warning']}")

    lines.extend(["", "## 利率与宏观观测"])
    if snapshot.observations:
        for item in snapshot.observations:
            date_text = item.observation_date.isoformat() if item.observation_date else "未知日期"
            stale_note = "，数据已过期" if item.is_stale else ""
            lines.append(f"- {item.indicator}: {item.value:g} {item.unit or ''}（{date_text}，[{item.source_name}]({item.source_url}){stale_note}）")
    else:
        lines.append("- 暂无可用 FRED 观测。")

    lines.extend(["", "## 市场快照"])
    for item in snapshot.market_data:
        one_day = item.get("change_1d")
        five_day = item.get("change_5d")
        lines.append(
            f"- {item['indicator']} ({item['symbol']}): {item['value']:.2f}；"
            f"1日 {one_day if one_day is not None else 'N/A'}%，5日 {five_day if five_day is not None else 'N/A'}%"
        )
    if not snapshot.market_data:
        lines.append("- 暂无可用市场数据。")

    drivers = horizon.get("drivers") or []
    if drivers:
        lines.extend(["", "## 规则证据"])
        lines.extend(f"- {driver}" for driver in drivers)
    if snapshot.missing_indicators or snapshot.warnings:
        lines.extend(["", "## 数据缺口"])
        if snapshot.missing_indicators:
            lines.append("- 缺少指标：" + "、".join(snapshot.missing_indicators))
        lines.extend(f"- {warning}" for warning in snapshot.warnings)
    return "\n".join(lines) + "\n"


def render_ai_explanation(explanation: USMacroAIExplanation) -> str:
    lines = ["\n## AI 受限解释", f"- 核心逻辑：{explanation.core_logic}"]
    for title, values in (("利多因素", explanation.bullish_factors), ("利空因素", explanation.bearish_factors), ("行业影响", explanation.sector_impacts), ("风险", explanation.risks), ("失效条件", explanation.invalidation_conditions)):
        if values:
            lines.append(f"- {title}：" + "；".join(values))
    return "\n".join(lines) + "\n"
