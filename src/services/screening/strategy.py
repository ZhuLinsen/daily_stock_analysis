# -*- coding: utf-8 -*-
# Derived from AlphaSift revision 9f522747caafd3c0b1ddb7e14d5cf44c8580b6cf.
# Licensed under Apache-2.0 and modified for daily_stock_analysis.
"""Strategy YAML loader."""

import hashlib
import logging
from dataclasses import asdict, fields
from pathlib import Path

import yaml

from src.services.screening.models import (
    HardFilterConfig,
    ScreeningConfig,
    Strategy,
    StrategyInfo,
    StrategyStyle,
)

logger = logging.getLogger(__name__)
_TOP_LEVEL_KEYS = {
    "name",
    "display_name",
    "description",
    "version",
    "category",
    "tags",
    "analysis_skills",
    "style",
    "screening",
}
_SCREENING_KEYS = {
    "enabled",
    "market_scope",
    "hard_filters",
    "tech_weight",
    "factor_weights",
    "scoring_profile",
    "risk_profile",
    "portfolio_profile",
    "scorecard_profile",
    "event_profile",
    "ranking_hints",
    "max_output",
}
_HARD_FILTER_KEYS = set(HardFilterConfig.__dataclass_fields__.keys())
_SCORING_PROFILE_KEYS = {
    "momentum_base",
    "momentum_intraday_slope",
    "momentum_chase_start_pct",
    "momentum_chase_penalty_slope",
    "momentum_downside_start_pct",
    "momentum_downside_penalty_slope",
    "momentum_60d_base",
    "momentum_60d_slope",
    "momentum_60d_overheat_pct",
    "momentum_60d_overheat_penalty_slope",
    "momentum_60d_breakdown_pct",
    "momentum_60d_breakdown_penalty_slope",
    "macd_bullish_bonus",
    "macd_bearish_penalty",
    "reversal_ideal_change_pct",
    "reversal_distance_penalty_slope",
    "reversal_collapse_start_pct",
    "reversal_collapse_penalty_slope",
    "reversal_chase_start_pct",
    "reversal_chase_penalty_slope",
    "rsi_oversold_bonus",
    "rsi_overbought_penalty",
    "activity_ideal_volume_ratio",
    "activity_volume_ratio_distance_slope",
    "activity_high_volume_ratio",
    "activity_high_volume_ratio_penalty_slope",
    "activity_ideal_turnover_rate",
    "activity_turnover_distance_slope",
    "activity_high_turnover_rate",
    "activity_high_turnover_penalty_slope",
    "stability_base",
    "stability_change_abs_penalty_slope",
    "stability_hot_change_pct",
    "stability_hot_change_penalty_slope",
    "stability_high_turnover_rate",
    "stability_high_turnover_penalty_slope",
    "stability_high_volume_ratio",
    "stability_high_volume_ratio_penalty_slope",
    "stability_invalid_pe_penalty",
    "stability_high_volatility_pct",
    "stability_high_volatility_penalty_slope",
    "stability_max_drawdown_floor_pct",
    "stability_drawdown_penalty_slope",
    "stability_high_atr_pct",
    "stability_high_atr_penalty_slope",
    "stability_low_daily_quality_score",
    "stability_low_daily_quality_penalty_slope",
    "stability_bad_daily_quality_flag_penalty",
    "theme_heat_unknown_score",
    "theme_heat_change_slope",
    "theme_heat_rank_bonus",
    "theme_heat_trend_min_observations",
    "theme_heat_trend_slope",
    "theme_heat_trend_bonus_cap",
    "theme_heat_cooling_penalty_slope",
    "theme_heat_cooling_penalty_cap",
    "theme_heat_persistence_min_score",
    "theme_heat_persistence_slope",
    "theme_heat_persistence_bonus_cap",
    "theme_heat_cooling_score_penalty_slope",
    "theme_heat_cooling_score_penalty_cap",
    "theme_heat_overheat_score",
    "theme_heat_overheat_penalty_slope",
}
_RISK_PROFILE_KEYS = {
    "chase_change_pct",
    "chase_points",
    "breakdown_change_pct",
    "breakdown_points",
    "abnormal_volume_ratio",
    "abnormal_volume_ratio_points",
    "high_turnover_rate",
    "high_turnover_points",
    "invalid_pe_points",
    "high_pb",
    "high_pb_points",
    "weak_signal_score",
    "weak_signal_points",
    "macd_bearish_points",
    "rsi_overbought_points",
    "low_llm_confidence",
    "low_llm_confidence_points",
    "llm_risk_points",
    "llm_risk_points_cap",
    "deep_risk_points",
    "deep_risk_points_cap",
    "low_daily_quality_score",
    "low_daily_quality_points",
    "bad_daily_quality_flag_points",
    "stale_daily_cache_points",
    "fallback_daily_errors_points",
    "fetch_failed_daily_points",
}
_PORTFOLIO_PROFILE_KEYS = {"max_same_bucket", "concentration_penalty", "buckets"}
_SCORECARD_PROFILE_KEYS = {
    "value_quality_value_min",
    "value_quality_stability_min",
    "value_quality_bonus",
    "capital_confirmed_momentum_min",
    "capital_confirmed_activity_min",
    "capital_confirmed_bonus",
    "controlled_reversal_min",
    "controlled_reversal_bonus",
    "hot_money_activity_min",
    "hot_money_stability_max",
    "hot_money_penalty",
    "volume_spike_ratio",
    "volume_spike_penalty",
    "high_llm_confidence",
    "high_llm_confidence_bonus",
    "low_llm_confidence",
    "low_llm_confidence_penalty",
    "catalyst_bonus",
    "catalyst_bonus_cap",
    "llm_risk_penalty",
    "llm_risk_penalty_cap",
    "score_delta_cap",
}
_EVENT_PROFILE_KEYS = {
    "preferred_event_tags",
    "avoided_event_tags",
    "preferred_announcement_categories",
    "avoided_announcement_categories",
    "source_weights",
    "notes",
}
_STYLE_KEYS = {
    "risk_profile",
    "holding_period",
    "execution_style",
    "market_regime",
    "capital_profile",
    "ui_badge",
}
_STRATEGY_DIR_CACHE: dict[
    Path,
    tuple[tuple[tuple[str, int, int, str], ...], dict[str, Strategy]],
] = {}


def load_strategy(filepath: Path) -> Strategy:
    """Load a screening strategy from a YAML file."""
    with open(filepath, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    if not isinstance(data, dict):
        raise ValueError(f"Invalid strategy file: {filepath}")

    _raise_unknown_keys(data, _TOP_LEVEL_KEYS, f"strategy file {filepath.name}")

    screening_data = data.get("screening", {})
    if not isinstance(screening_data, dict):
        raise ValueError(f"Invalid screening section in strategy file: {filepath}")
    _raise_unknown_keys(screening_data, _SCREENING_KEYS, f"screening section of {filepath.name}")

    hf_data = screening_data.get("hard_filters", {})
    if not isinstance(hf_data, dict):
        raise ValueError(f"Invalid hard_filters section in strategy file: {filepath}")
    _raise_unknown_keys(hf_data, _HARD_FILTER_KEYS, f"hard_filters section of {filepath.name}")

    hard_filters = HardFilterConfig(**hf_data)

    screening = ScreeningConfig(
        enabled=screening_data.get("enabled", False),
        market_scope=screening_data.get("market_scope", ["cn"]),
        hard_filters=hard_filters,
        tech_weight=screening_data.get("tech_weight", 0.35),
        factor_weights=screening_data.get("factor_weights", {}),
        scoring_profile=_optional_mapping(
            screening_data, "scoring_profile", filepath, allowed_keys=_SCORING_PROFILE_KEYS
        ),
        risk_profile=_optional_mapping(
            screening_data, "risk_profile", filepath, allowed_keys=_RISK_PROFILE_KEYS
        ),
        portfolio_profile=_optional_mapping(
            screening_data, "portfolio_profile", filepath, allowed_keys=_PORTFOLIO_PROFILE_KEYS
        ),
        scorecard_profile=_optional_mapping(
            screening_data, "scorecard_profile", filepath, allowed_keys=_SCORECARD_PROFILE_KEYS
        ),
        event_profile=_optional_mapping(
            screening_data, "event_profile", filepath, allowed_keys=_EVENT_PROFILE_KEYS
        ),
        ranking_hints=screening_data.get("ranking_hints", ""),
        max_output=screening_data.get("max_output", 5),
    )

    return Strategy(
        name=data.get("name", filepath.stem),
        display_name=data.get("display_name", data.get("name", filepath.stem)),
        description=data.get("description", ""),
        version=str(data.get("version", "1")),
        category=data.get("category", "trend"),
        tags=list(data.get("tags", []) or []),
        analysis_skills=_string_list(data.get("analysis_skills")),
        style=_strategy_style(data, filepath),
        screening=screening,
    )


def load_all_strategies(strategies_dir: Path) -> dict[str, Strategy]:
    """Load all strategies from a directory."""
    resolved_dir = strategies_dir.resolve()
    signature = _strategy_dir_signature(resolved_dir)
    cached = _STRATEGY_DIR_CACHE.get(resolved_dir)
    if cached is not None and cached[0] == signature:
        return dict(cached[1])

    strategies = {}
    if not strategies_dir.is_dir():
        _STRATEGY_DIR_CACHE[resolved_dir] = (signature, strategies)
        return strategies
    for f in sorted(strategies_dir.glob("*.yaml")):
        try:
            s = load_strategy(f)
            if s.screening.enabled:
                strategies[s.name] = s
        except Exception as e:
            logger.warning("Failed to load strategy %s: %s", f.name, e)
            continue
    _STRATEGY_DIR_CACHE[resolved_dir] = (signature, dict(strategies))
    return dict(strategies)


def _strategy_dir_signature(strategies_dir: Path) -> tuple[tuple[str, int, int, str], ...]:
    if not strategies_dir.is_dir():
        return ()
    signature = []
    for filepath in sorted(strategies_dir.glob("*.yaml")):
        try:
            stat = filepath.stat()
            digest = hashlib.sha256(filepath.read_bytes()).hexdigest()
        except OSError:
            continue
        signature.append((filepath.name, stat.st_mtime_ns, stat.st_size, digest))
    return tuple(signature)


def list_strategies(strategies_dir: Path | None = None) -> list[StrategyInfo]:
    """List available screening strategies."""
    from src.services.screening.config import Config
    from src.services.screening.filter import requires_daily_features

    if strategies_dir is None:
        strategies_dir = Config.from_env().strategies_dir

    strategies = load_all_strategies(strategies_dir)
    infos: list[StrategyInfo] = []
    for s in strategies.values():
        daily_required = requires_daily_features(s.screening.hard_filters)
        infos.append(StrategyInfo(
            name=s.name,
            display_name=s.display_name,
            description=s.description,
            version=s.version,
            category=s.category,
            tags=s.tags,
            analysis_skills=s.analysis_skills,
            market_scope=s.screening.market_scope,
            requires_daily_features=daily_required,
            data_requirements=_strategy_data_requirements(s, daily_required=daily_required),
            required_snapshot_fields=_required_snapshot_fields(s.screening.hard_filters),
            required_daily_fields=_required_daily_fields(s.screening.hard_filters),
            active_filters=_active_hard_filters(s.screening.hard_filters),
            factor_weights={key: float(value) for key, value in s.screening.factor_weights.items()},
            profile_keys=_strategy_profile_keys(s.screening),
            style=_style_to_dict(s.style),
        ))
    return infos


def strategy_facets(strategies_dir: Path | None = None) -> dict[str, object]:
    """Return UI-ready filter facets for the strategy catalog."""
    return strategy_facets_from_infos(list_strategies(strategies_dir))


def strategy_facets_from_infos(strategies: list[StrategyInfo]) -> dict[str, object]:
    """Build strategy catalog facets from already loaded strategy metadata."""
    return {
        "schema_version": 1,
        "strategy_count": len(strategies),
        "daily_strategy_count": sum(1 for item in strategies if item.requires_daily_features),
        "facets": [
            _strategy_facet(
                strategies,
                name="category",
                query_param="category",
                multi=False,
                values_fn=lambda item: [item.category],
            ),
            _strategy_facet(
                strategies,
                name="risk_profile",
                query_param="risk_profile",
                multi=False,
                values_fn=lambda item: [str(item.style.get("risk_profile") or "")],
            ),
            _strategy_facet(
                strategies,
                name="holding_period",
                query_param="holding_period",
                multi=False,
                values_fn=lambda item: [str(item.style.get("holding_period") or "")],
            ),
            _strategy_facet(
                strategies,
                name="execution_style",
                query_param="execution_style",
                multi=False,
                values_fn=lambda item: [str(item.style.get("execution_style") or "")],
            ),
            _strategy_facet(
                strategies,
                name="capital_profile",
                query_param="capital_profile",
                multi=False,
                values_fn=lambda item: [str(item.style.get("capital_profile") or "")],
            ),
            _strategy_facet(
                strategies,
                name="market_regime",
                query_param="market_regime",
                multi=True,
                values_fn=lambda item: item.style.get("market_regime", []),
            ),
            _strategy_facet(
                strategies,
                name="data_requirement",
                query_param="data_requirement",
                multi=True,
                values_fn=lambda item: item.data_requirements,
            ),
            _strategy_facet(
                strategies,
                name="tag",
                query_param="tag",
                multi=True,
                values_fn=lambda item: item.tags,
            ),
            _strategy_facet(
                strategies,
                name="daily_required",
                query_param="daily_required",
                multi=False,
                values_fn=lambda item: [str(bool(item.requires_daily_features)).lower()],
            ),
            _strategy_facet(
                strategies,
                name="required_snapshot_field",
                query_param="",
                multi=True,
                filterable=False,
                values_fn=lambda item: item.required_snapshot_fields,
            ),
            _strategy_facet(
                strategies,
                name="required_daily_field",
                query_param="",
                multi=True,
                filterable=False,
                values_fn=lambda item: item.required_daily_fields,
            ),
        ],
    }


def _strategy_facet(
    strategies: list[StrategyInfo],
    *,
    name: str,
    query_param: str,
    multi: bool,
    values_fn,
    filterable: bool = True,
) -> dict[str, object]:
    groups: dict[str, list[str]] = {}
    for item in strategies:
        raw_values = values_fn(item) or []
        if isinstance(raw_values, str):
            raw_values = [raw_values]
        for raw_value in raw_values:
            value = str(raw_value).strip()
            if value:
                groups.setdefault(value, []).append(item.name)
    values = [
        {
            "value": value,
            "count": len(strategy_names),
            "strategies": sorted(strategy_names),
        }
        for value, strategy_names in groups.items()
    ]
    values.sort(key=lambda item: (-int(item["count"]), str(item["value"])))
    return {
        "name": name,
        "query_param": query_param,
        "filterable": bool(filterable),
        "multi": bool(multi),
        "values": values,
    }


def match_strategies(
    strategies_dir: Path | None = None,
    *,
    risk_profile: str = "",
    holding_period: str = "",
    execution_style: str = "",
    market_regime: list[str] | None = None,
    capital_profile: str = "",
    data_requirements: list[str] | None = None,
    tags: list[str] | None = None,
    category: str = "",
    daily_required: bool | None = None,
    strict: bool = False,
    limit: int | None = None,
) -> list[dict[str, object]]:
    """Rank strategies by UI/agent-facing selection preferences."""
    criteria = {
        "risk_profile": risk_profile,
        "holding_period": holding_period,
        "execution_style": execution_style,
        "capital_profile": capital_profile,
        "category": category,
    }
    regimes = _normalized_values(market_regime)
    required_data = _normalized_values(data_requirements)
    required_tags = _normalized_values(tags)
    results: list[dict[str, object]] = []

    for info in list_strategies(strategies_dir):
        score = 0.0
        matched: list[str] = []
        missing: list[str] = []
        style = info.style or {}

        score += _match_single(
            criteria["risk_profile"],
            str(style.get("risk_profile") or ""),
            "risk_profile",
            3.0,
            matched,
            missing,
        )
        score += _match_single(
            criteria["holding_period"],
            str(style.get("holding_period") or ""),
            "holding_period",
            2.0,
            matched,
            missing,
        )
        score += _match_single(
            criteria["execution_style"],
            str(style.get("execution_style") or ""),
            "execution_style",
            2.0,
            matched,
            missing,
        )
        score += _match_single(
            criteria["capital_profile"],
            str(style.get("capital_profile") or ""),
            "capital_profile",
            1.0,
            matched,
            missing,
        )
        score += _match_single(
            criteria["category"],
            info.category,
            "category",
            1.5,
            matched,
            missing,
        )

        available_regimes = _normalized_values(style.get("market_regime", []))
        score += _match_many(regimes, available_regimes, "market_regime", 1.0, matched, missing)
        score += _match_many(
            required_data,
            _normalized_values(info.data_requirements),
            "data_requirement",
            1.0,
            matched,
            missing,
        )
        score += _match_many(required_tags, _normalized_values(info.tags), "tag", 1.0, matched, missing)
        if daily_required is not None:
            if bool(info.requires_daily_features) == daily_required:
                score += 1.0
                matched.append(f"daily_required:{str(daily_required).lower()}")
            else:
                missing.append(f"daily_required:{str(daily_required).lower()}")

        if strict and missing:
            continue
        results.append({
            "name": info.name,
            "display_name": info.display_name,
            "description": info.description,
            "version": info.version,
            "category": info.category,
            "tags": list(info.tags),
            "market_scope": list(info.market_scope),
            "style": dict(info.style),
            "data_requirements": list(info.data_requirements),
            "requires_daily_features": info.requires_daily_features,
            "required_snapshot_fields": list(info.required_snapshot_fields),
            "required_daily_fields": list(info.required_daily_fields),
            "factor_weights": dict(info.factor_weights),
            "active_filters": list(info.active_filters),
            "profile_keys": dict(info.profile_keys),
            "score": round(score, 2),
            "matched": matched,
            "missing": missing,
        })

    results.sort(key=lambda item: (-float(item["score"]), str(item["name"])))
    if limit is not None:
        results = results[:max(limit, 0)]
    return results


def compare_strategies(
    base_name: str,
    target_name: str,
    strategies_dir: Path | None = None,
) -> dict[str, object]:
    """Compare two enabled strategies for strategy review and UI diff views."""
    from src.services.screening.config import Config
    from src.services.screening.filter import requires_daily_features

    if strategies_dir is None:
        strategies_dir = Config.from_env().strategies_dir
    strategies = load_all_strategies(strategies_dir)
    try:
        base = strategies[base_name]
        target = strategies[target_name]
    except KeyError as exc:
        missing = exc.args[0]
        raise ValueError(f"Strategy '{missing}' not found") from exc

    base_daily = requires_daily_features(base.screening.hard_filters)
    target_daily = requires_daily_features(target.screening.hard_filters)
    differences = {
        "identity": _mapping_diff(
            {
                "version": base.version,
                "category": base.category,
                "market_scope": list(base.screening.market_scope),
                "requires_daily_features": base_daily,
            },
            {
                "version": target.version,
                "category": target.category,
                "market_scope": list(target.screening.market_scope),
                "requires_daily_features": target_daily,
            },
        ),
        "tags": _list_diff(base.tags, target.tags),
        "style": _mapping_diff(_style_to_dict(base.style), _style_to_dict(target.style)),
        "data_requirements": _list_diff(
            _strategy_data_requirements(base, daily_required=base_daily),
            _strategy_data_requirements(target, daily_required=target_daily),
        ),
        "required_snapshot_fields": _list_diff(
            _required_snapshot_fields(base.screening.hard_filters),
            _required_snapshot_fields(target.screening.hard_filters),
        ),
        "required_daily_fields": _list_diff(
            _required_daily_fields(base.screening.hard_filters),
            _required_daily_fields(target.screening.hard_filters),
        ),
        "active_filters": _list_diff(
            _active_hard_filters(base.screening.hard_filters),
            _active_hard_filters(target.screening.hard_filters),
        ),
        "hard_filter_values": _mapping_diff(
            _active_filter_values(base.screening.hard_filters),
            _active_filter_values(target.screening.hard_filters),
        ),
        "factor_weights": _numeric_mapping_diff(
            base.screening.factor_weights,
            target.screening.factor_weights,
        ),
        "profile_keys": _nested_list_diff(
            _strategy_profile_keys(base.screening),
            _strategy_profile_keys(target.screening),
        ),
    }
    return {
        "base": _strategy_compare_summary(base, daily_required=base_daily),
        "target": _strategy_compare_summary(target, daily_required=target_daily),
        "differences": differences,
        "summary": _strategy_compare_summary_notes(differences),
    }


def _strategy_data_requirements(strategy: Strategy, *, daily_required: bool) -> list[str]:
    requirements = ["snapshot"]
    if daily_required:
        requirements.append("daily_k")
    factors = set(strategy.screening.factor_weights)
    if factors & {"theme_heat", "topic_alignment"}:
        requirements.append("industry_context")
    if strategy.screening.event_profile:
        requirements.append("event_context")
    return requirements


def _strategy_compare_summary(strategy: Strategy, *, daily_required: bool) -> dict[str, object]:
    return {
        "name": strategy.name,
        "display_name": strategy.display_name,
        "version": strategy.version,
        "category": strategy.category,
        "tags": list(strategy.tags),
        "style": _style_to_dict(strategy.style),
        "data_requirements": _strategy_data_requirements(strategy, daily_required=daily_required),
        "requires_daily_features": daily_required,
        "active_filters": _active_hard_filters(strategy.screening.hard_filters),
        "factor_weights": {key: float(value) for key, value in strategy.screening.factor_weights.items()},
        "profile_keys": _strategy_profile_keys(strategy.screening),
    }


def _strategy_compare_summary_notes(differences: dict[str, object]) -> dict[str, object]:
    changed_sections = [
        name
        for name, value in differences.items()
        if _diff_has_changes(value)
    ]
    notes: list[str] = []
    data_diff = differences.get("data_requirements", {})
    if isinstance(data_diff, dict):
        added = data_diff.get("added", [])
        removed = data_diff.get("removed", [])
        if added:
            notes.append("target_requires_additional_data:" + ",".join(str(item) for item in added))
        if removed:
            notes.append("target_removes_data:" + ",".join(str(item) for item in removed))
    identity_diff = differences.get("identity", {})
    if isinstance(identity_diff, dict) and "requires_daily_features" in identity_diff.get("changed", {}):
        notes.append("daily_feature_requirement_changed")
    return {
        "changed_sections": changed_sections,
        "change_count": len(changed_sections),
        "compatibility_notes": notes,
    }


def _diff_has_changes(value: object) -> bool:
    if not isinstance(value, dict):
        return bool(value)
    for key in ("added", "removed", "changed"):
        item = value.get(key)
        if item:
            return True
    for item in value.values():
        if isinstance(item, dict) and _diff_has_changes(item):
            return True
    return False


def _active_filter_values(filters_config: HardFilterConfig) -> dict[str, object]:
    active = set(_active_hard_filters(filters_config))
    values = asdict(filters_config)
    return {
        key: value
        for key, value in values.items()
        if key in active
    }


def _list_diff(base: list[object], target: list[object]) -> dict[str, list[object]]:
    base_values = list(dict.fromkeys(base))
    target_values = list(dict.fromkeys(target))
    return {
        "shared": [item for item in base_values if item in target_values],
        "added": [item for item in target_values if item not in base_values],
        "removed": [item for item in base_values if item not in target_values],
    }


def _mapping_diff(base: dict[str, object], target: dict[str, object]) -> dict[str, object]:
    base_keys = set(base)
    target_keys = set(target)
    changed = {}
    for key in sorted(base_keys & target_keys):
        if base[key] != target[key]:
            changed[key] = {
                "base": base[key],
                "target": target[key],
            }
    return {
        "added": {key: target[key] for key in sorted(target_keys - base_keys)},
        "removed": {key: base[key] for key in sorted(base_keys - target_keys)},
        "changed": changed,
    }


def _numeric_mapping_diff(base: dict[str, object], target: dict[str, object]) -> dict[str, object]:
    diff = _mapping_diff(
        {key: float(value) for key, value in base.items()},
        {key: float(value) for key, value in target.items()},
    )
    changed = diff.get("changed", {})
    if isinstance(changed, dict):
        for item in changed.values():
            if isinstance(item, dict):
                item["delta"] = round(float(item["target"]) - float(item["base"]), 6)
    return diff


def _nested_list_diff(
    base: dict[str, list[str]],
    target: dict[str, list[str]],
) -> dict[str, object]:
    keys = sorted(set(base) | set(target))
    return {
        key: _list_diff(base.get(key, []), target.get(key, []))
        for key in keys
    }


def _active_hard_filters(filters_config: HardFilterConfig) -> list[str]:
    active: list[str] = []
    defaults = HardFilterConfig()
    for item in fields(HardFilterConfig):
        name = item.name
        value = getattr(filters_config, name)
        default = getattr(defaults, name)
        if name == "exclude_st":
            if bool(value):
                active.append(name)
            continue
        if value != default and value is not None and value is not False:
            active.append(name)
    return active


def _required_snapshot_fields(filters_config: HardFilterConfig) -> list[str]:
    fields: list[str] = []
    if filters_config.exclude_st:
        fields.append("name")
    if filters_config.amount_min is not None:
        fields.append("amount")
    if filters_config.price_min is not None or filters_config.price_max is not None:
        fields.append("price")
    if filters_config.market_cap_min is not None or filters_config.market_cap_max is not None:
        fields.append("total_mv")
    if filters_config.pe_ttm_min is not None or filters_config.pe_ttm_max is not None:
        fields.append("pe_ratio")
    if filters_config.pb_min is not None or filters_config.pb_max is not None:
        fields.append("pb_ratio")
    if filters_config.volume_ratio_min is not None:
        fields.append("volume_ratio")
    if filters_config.turnover_rate_min is not None:
        fields.append("turnover_rate")
    if filters_config.change_pct_min is not None or filters_config.change_pct_max is not None:
        fields.append("change_pct")
    return list(dict.fromkeys(fields))


def _required_daily_fields(filters_config: HardFilterConfig) -> list[str]:
    checks = [
        ("change_60d", filters_config.change_60d_min is not None or filters_config.change_60d_max is not None),
        ("ma_bullish", filters_config.require_ma_bullish),
        ("price_above_ma20", filters_config.require_price_above_ma20),
        ("signal_score", filters_config.signal_score_min is not None),
        ("macd_status", bool(filters_config.macd_status_whitelist)),
        ("rsi_status", bool(filters_config.rsi_status_whitelist)),
        (
            "breakout_20d_pct",
            filters_config.breakout_20d_pct_min is not None
            or filters_config.breakout_20d_pct_max is not None,
        ),
        ("range_20d_pct", filters_config.range_20d_pct_max is not None),
        (
            "volume_ratio_20d",
            filters_config.volume_ratio_20d_min is not None
            or filters_config.volume_ratio_20d_max is not None,
        ),
        ("body_pct", filters_config.body_pct_min is not None or filters_config.body_pct_max is not None),
        (
            "pullback_to_ma20_pct",
            filters_config.pullback_to_ma20_pct_min is not None
            or filters_config.pullback_to_ma20_pct_max is not None,
        ),
        (
            "consolidation_days_20d",
            filters_config.consolidation_days_20d_min is not None
            or filters_config.consolidation_days_20d_max is not None,
        ),
        (
            "volatility_20d_pct",
            filters_config.volatility_20d_pct_min is not None
            or filters_config.volatility_20d_pct_max is not None,
        ),
        (
            "max_drawdown_20d_pct",
            filters_config.max_drawdown_20d_pct_min is not None
            or filters_config.max_drawdown_20d_pct_max is not None,
        ),
        ("atr_20_pct", filters_config.atr_20_pct_min is not None or filters_config.atr_20_pct_max is not None),
    ]
    return [field for field, enabled in checks if enabled]


def _strategy_profile_keys(screening: ScreeningConfig) -> dict[str, list[str]]:
    profile_values = {
        "scoring": screening.scoring_profile,
        "risk": screening.risk_profile,
        "portfolio": screening.portfolio_profile,
        "scorecard": screening.scorecard_profile,
        "event": screening.event_profile,
    }
    return {
        name: sorted(value)
        for name, value in profile_values.items()
        if value
    }


def _strategy_style(data: dict, filepath: Path) -> StrategyStyle:
    raw = data.get("style", {})
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise ValueError(f"Invalid style section in strategy file: {filepath}")
    _raise_unknown_keys(raw, _STYLE_KEYS, f"style section of {filepath.name}")
    inferred = _infer_strategy_style(
        category=str(data.get("category", "trend")),
        tags=[str(item) for item in data.get("tags", []) or []],
    )
    return StrategyStyle(
        risk_profile=str(raw.get("risk_profile") or inferred.risk_profile),
        holding_period=str(raw.get("holding_period") or inferred.holding_period),
        execution_style=str(raw.get("execution_style") or inferred.execution_style),
        market_regime=_string_list(raw.get("market_regime") or inferred.market_regime),
        capital_profile=str(raw.get("capital_profile") or inferred.capital_profile),
        ui_badge=str(raw.get("ui_badge") or inferred.ui_badge),
    )


def _infer_strategy_style(*, category: str, tags: list[str]) -> StrategyStyle:
    tag_set = {tag.lower() for tag in tags}
    if category == "value" or "defensive" in tag_set:
        risk_profile = "defensive"
    elif category in {"momentum", "trend"}:
        risk_profile = "aggressive"
    else:
        risk_profile = "balanced"

    if "short_term" in tag_set or category == "momentum":
        holding_period = "short_term"
    elif "daily_k" in tag_set or "trend" in tag_set:
        holding_period = "swing"
    else:
        holding_period = "watchlist"

    if category == "value":
        execution_style = "mean_reversion"
    elif category == "reversal":
        execution_style = "reversal"
    elif category in {"momentum", "trend"}:
        execution_style = "trend_following"
    else:
        execution_style = "multi_factor"

    if risk_profile == "defensive":
        market_regime = ["risk_off", "range_bound"]
    elif execution_style == "trend_following":
        market_regime = ["risk_on", "trend"]
    elif execution_style == "reversal":
        market_regime = ["oversold_repair", "range_bound"]
    else:
        market_regime = ["neutral"]

    return StrategyStyle(
        risk_profile=risk_profile,
        holding_period=holding_period,
        execution_style=execution_style,
        market_regime=market_regime,
        capital_profile="medium_liquidity",
        ui_badge=category,
    )


def _style_to_dict(style: StrategyStyle) -> dict[str, object]:
    return {
        "risk_profile": style.risk_profile,
        "holding_period": style.holding_period,
        "execution_style": style.execution_style,
        "market_regime": list(style.market_regime),
        "capital_profile": style.capital_profile,
        "ui_badge": style.ui_badge,
    }


def _string_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    return []


def _normalized_values(values: object) -> list[str]:
    raw = _string_list(values)
    normalized = []
    seen = set()
    for item in raw:
        token = item.strip().lower()
        if not token or token in seen:
            continue
        normalized.append(token)
        seen.add(token)
    return normalized


def _match_single(
    expected: str,
    actual: str,
    label: str,
    weight: float,
    matched: list[str],
    missing: list[str],
) -> float:
    expected_normalized = expected.strip().lower()
    if not expected_normalized:
        return 0.0
    if actual.strip().lower() == expected_normalized:
        matched.append(f"{label}:{expected_normalized}")
        return weight
    missing.append(f"{label}:{expected_normalized}")
    return 0.0


def _match_many(
    expected: list[str],
    actual: list[str],
    label: str,
    weight: float,
    matched: list[str],
    missing: list[str],
) -> float:
    if not expected:
        return 0.0
    actual_set = set(actual)
    score = 0.0
    for item in expected:
        if item in actual_set:
            matched.append(f"{label}:{item}")
            score += weight
        else:
            missing.append(f"{label}:{item}")
    return score


def _raise_unknown_keys(data: dict, allowed_keys: set[str], context: str) -> None:
    unknown_keys = sorted(set(data.keys()) - allowed_keys)
    if unknown_keys:
        raise ValueError(
            f"Unknown keys in {context}: {', '.join(unknown_keys)}"
        )


def _optional_mapping(
    data: dict,
    key: str,
    filepath: Path,
    *,
    allowed_keys: set[str],
) -> dict:
    value = data.get(key, {})
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"Invalid {key} section in strategy file: {filepath}")
    _raise_unknown_keys(value, allowed_keys, f"{key} section of {filepath.name}")
    return value
