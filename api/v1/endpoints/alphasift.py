# -*- coding: utf-8 -*-
"""Optional AlphaSift stock screening endpoint."""

from __future__ import annotations

import importlib
import inspect
import logging
import math
import os
import subprocess
import sys
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from api.deps import get_config_dep
from src.config import Config, DEFAULT_ALPHASIFT_INSTALL_SPEC
from src.auth import COOKIE_NAME, is_auth_enabled, verify_session

router = APIRouter()
logger = logging.getLogger(__name__)

ALPHASIFT_DSA_ADAPTER_MODULE = "alphasift.dsa_adapter"
ALPHASIFT_EXPECTED_MISSING_MODULES = frozenset({"alphasift", ALPHASIFT_DSA_ADAPTER_MODULE})
ALLOWED_ALPHASIFT_INSTALL_SPECS = frozenset({DEFAULT_ALPHASIFT_INSTALL_SPEC})


class AlphaSiftScreenRequest(BaseModel):
    market: str = Field("cn", min_length=1, max_length=16)
    strategy: str = Field("dual_low", min_length=1, max_length=64)
    max_results: int = Field(20, ge=1, le=100)


class AlphaSiftStrategyResponse(BaseModel):
    id: str
    name: str = ""
    title: str = ""
    description: str = ""
    category: str = ""
    tag: str = ""
    tags: List[str] = Field(default_factory=list)
    market_scope: List[str] = Field(default_factory=list)
    market: str = ""


@router.get("/status")
def alphasift_status(config: Config = Depends(get_config_dep)) -> Dict[str, Any]:
    adapter_status, available, diagnostics = _get_alphasift_status_snapshot()
    payload = {
        "enabled": bool(config.alphasift_enabled),
        "available": available,
        "install_spec_is_default": _is_default_alphasift_install_spec(config.alphasift_install_spec),
        "contract_version": adapter_status.get("contract_version"),
        "version": adapter_status.get("version"),
        "strategy_count": adapter_status.get("strategy_count"),
    }
    if diagnostics:
        payload["diagnostics"] = diagnostics
    return payload


@router.get("/strategies")
def alphasift_strategies(config: Config = Depends(get_config_dep)) -> Dict[str, Any]:
    _ensure_alphasift_enabled(config)
    strategies = _list_strategies()
    return {
        "enabled": True,
        "strategies": strategies,
        "strategy_count": len(strategies),
    }


def _require_admin_session_for_install(request: Request) -> None:
    if not is_auth_enabled():
        raise HTTPException(
            status_code=403,
            detail={
                "error": "alphasift_install_auth_required",
                "message": "自动安装 AlphaSift 需要先开启 ADMIN_AUTH_ENABLED 并完成管理员登录。",
            },
        )

    session = request.cookies.get(COOKIE_NAME, "")
    if not verify_session(session):
        raise HTTPException(
            status_code=401,
            detail={
                "error": "alphasift_install_unauthorized",
                "message": "自动安装 AlphaSift 需要有效的管理员会话。",
            },
        )


@router.post("/install")
def alphasift_install(
    config: Config = Depends(get_config_dep),
    _: None = Depends(_require_admin_session_for_install),
) -> Dict[str, Any]:
    _ensure_alphasift_enabled(config)
    return _install_alphasift(config)


def _install_alphasift(config: Config) -> Dict[str, Any]:
    install_spec_is_default = _is_default_alphasift_install_spec(config.alphasift_install_spec)
    if _is_alphasift_available():
        _get_dsa_adapter()
        return _build_install_response(
            already_installed=True,
            install_spec_is_default=install_spec_is_default,
        )

    install_spec = _validate_install_spec(config.alphasift_install_spec)

    try:
        completed = subprocess.run(
            [sys.executable, "-m", "pip", "install", install_spec],
            check=False,
            capture_output=True,
            text=True,
            timeout=300,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=424,
            detail={"error": "alphasift_install_failed", "message": f"自动安装 AlphaSift 失败：{exc}"},
        ) from exc

    if completed.returncode != 0:
        stderr = (completed.stderr or "").strip()
        stdout = (completed.stdout or "").strip()
        detail = stderr or stdout or f"pip exited with code {completed.returncode}"
        raise HTTPException(
            status_code=424,
            detail={
                "error": "alphasift_install_failed",
                "message": f"自动安装 AlphaSift 失败：{detail}",
            },
        )

    importlib.invalidate_caches()
    adapter_status = _call_alphasift_status()
    if not _is_adapter_available(adapter_status):
        raise HTTPException(
            status_code=424,
            detail={"error": "alphasift_unavailable", "message": "AlphaSift 安装完成，但适配层当前不可用（available=false）。请检查当前 Python 环境和安装状态后重试。"},
        )
    _get_dsa_adapter()

    return _build_install_response(
        already_installed=False,
        install_spec_is_default=_is_default_alphasift_install_spec(install_spec),
    )


def _validate_install_spec(raw_install_spec: str) -> str:
    install_spec = (raw_install_spec or "").strip()
    if not install_spec or install_spec.lower() == "alphasift":
        raise HTTPException(
            status_code=424,
            detail={
                "error": "alphasift_install_spec_missing",
                "message": f"请先将 ALPHASIFT_INSTALL_SPEC 配置为受信任来源：{DEFAULT_ALPHASIFT_INSTALL_SPEC}。",
            },
        )

    if install_spec not in ALLOWED_ALPHASIFT_INSTALL_SPECS:
        raise HTTPException(
            status_code=403,
            detail={
                "error": "alphasift_install_spec_not_allowed",
                "message": (
                    "出于安全考虑，自动安装 AlphaSift 仅允许使用受信任来源："
                    f"{DEFAULT_ALPHASIFT_INSTALL_SPEC}。如需使用本地路径或 wheel，请先手动安装到当前 Python 环境。"
                ),
            },
        )

    return install_spec


@router.post("/screen")
def alphasift_screen(
    request: AlphaSiftScreenRequest,
    config: Config = Depends(get_config_dep),
) -> Dict[str, Any]:
    _ensure_alphasift_enabled(config)
    _ensure_supported_market(request.market)
    _ensure_supported_strategy(request.strategy)

    adapter = _get_dsa_adapter()
    screen = _get_adapter_callable(adapter, "screen", "screen() 不可调用。")
    try:
        raw = _call_alphasift_screen(screen, request.strategy, request.market, request.max_results)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"error": "alphasift_screen_rejected", "message": str(exc)},
        ) from exc
    except (TypeError, KeyError) as exc:
        raise HTTPException(
            status_code=422,
            detail={"error": "alphasift_invalid_input", "message": f"AlphaSift 参数非法：{exc}"},
        ) from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=424,
            detail={"error": "alphasift_screen_failed", "message": f"AlphaSift 选股运行失败：{exc}"},
        ) from exc

    raw_data = _to_plain(raw)
    if not isinstance(raw_data, dict):
        raw_data = {"candidates": raw_data}
    raw_data = _remove_non_finite_json_values(raw_data)

    candidates = _normalize_candidates(raw_data)
    selected = candidates[: request.max_results]
    return {
        "enabled": True,
        "candidates": selected,
        "candidate_count": len(selected),
        "run_id": raw_data.get("run_id"),
        "strategy": raw_data.get("strategy") or request.strategy,
        "market": raw_data.get("market") or request.market,
        "snapshot_count": raw_data.get("snapshot_count"),
        "after_filter_count": raw_data.get("after_filter_count"),
        "llm_ranked": raw_data.get("llm_ranked"),
        "llm_market_view": raw_data.get("llm_market_view") or "",
        "llm_selection_logic": raw_data.get("llm_selection_logic") or "",
        "llm_portfolio_risk": raw_data.get("llm_portfolio_risk") or "",
        "llm_coverage": raw_data.get("llm_coverage"),
        "llm_parse_errors": raw_data.get("llm_parse_errors") or [],
        "warnings": raw_data.get("warnings") or [],
        "source_errors": raw_data.get("source_errors") or [],
    }


def _ensure_alphasift_enabled(config: Config) -> None:
    if not config.alphasift_enabled:
        raise HTTPException(
            status_code=403,
            detail={"error": "alphasift_disabled", "message": "ALPHASIFT_ENABLED is false."},
        )


def _is_alphasift_available() -> bool:
    _, available, _ = _get_alphasift_status_snapshot()
    return available


def _get_alphasift_status_snapshot() -> Tuple[Dict[str, Any], bool, Optional[Dict[str, str]]]:
    try:
        adapter_status = _call_alphasift_status()
    except HTTPException as exc:
        return {}, False, _extract_alphasift_diagnostics(exc)
    except Exception as exc:
        diagnostics = _log_unexpected_alphasift_exception("status_probe", exc)
        return {}, False, diagnostics

    return adapter_status, _is_adapter_available(adapter_status), None


def _is_adapter_available(adapter_status: Any) -> bool:
    if isinstance(adapter_status, dict):
        return bool(adapter_status.get("available", True))
    return True


def _import_alphasift() -> Any:
    try:
        _prepare_alphasift_runtime_env()
        return importlib.import_module(ALPHASIFT_DSA_ADAPTER_MODULE)
    except ModuleNotFoundError as exc:
        if _is_expected_alphasift_missing(exc):
            raise _alphasift_unavailable_exception(
                f"AlphaSift 未安装或未挂载到当前 Python 环境，无法导入 {ALPHASIFT_DSA_ADAPTER_MODULE}：{exc}"
            ) from exc
        diagnostics = _log_unexpected_alphasift_exception("import_adapter", exc)
        raise _alphasift_unavailable_exception(
            f"AlphaSift 适配层导入失败，请检查依赖完整性和当前 Python 环境：{exc}",
            diagnostics=diagnostics,
        ) from exc
    except Exception as exc:
        diagnostics = _log_unexpected_alphasift_exception("import_adapter", exc)
        raise _alphasift_unavailable_exception(
            f"AlphaSift 适配层导入失败，请检查依赖完整性和当前 Python 环境：{exc}",
            diagnostics=diagnostics,
        ) from exc


def _prepare_alphasift_runtime_env() -> None:
    if os.getenv("STRATEGIES_DIR"):
        return

    spec = importlib.util.find_spec("alphasift")
    if not spec or not spec.origin:
        return

    package_strategies_dir = Path(spec.origin).resolve().parent / "strategies"
    if package_strategies_dir.is_dir():
        os.environ["STRATEGIES_DIR"] = str(package_strategies_dir)


def _get_dsa_adapter() -> Any:
    adapter = _import_alphasift()
    for attr in ("get_status", "list_strategies", "screen"):
        _get_adapter_callable(adapter, attr, f"{attr}() 不可调用。")
    return adapter


def _get_adapter_callable(adapter: Any, name: str, missing_error: str) -> Any:
    callable_obj = getattr(adapter, name, None)
    if not callable(callable_obj):
        raise HTTPException(
            status_code=424,
            detail={"error": "alphasift_unavailable", "message": f"已导入 alphasift 适配层，但 {missing_error}"},
        )
    return callable_obj


def _call_alphasift_status() -> Dict[str, Any]:
    adapter = _import_alphasift()
    try:
        get_status = _get_adapter_callable(adapter, "get_status", "get_status() 不可调用。")
    except HTTPException as exc:
        diagnostics = _log_unexpected_alphasift_exception("get_status_callable", exc)
        raise _alphasift_unavailable_exception(
            "AlphaSift 适配层 get_status 不可调用，请检查适配层版本。",
            diagnostics=diagnostics,
        ) from exc
    try:
        result = _to_plain(get_status())
    except Exception as exc:
        diagnostics = _log_unexpected_alphasift_exception("get_status", exc)
        raise _alphasift_unavailable_exception(
            f"AlphaSift 适配层 get_status 调用失败：{exc}",
            diagnostics=diagnostics,
        ) from exc
    if not isinstance(result, dict):
        exc = TypeError(f"get_status returned {type(result).__name__}, expected dict")
        diagnostics = _log_unexpected_alphasift_exception("get_status_result", exc)
        raise _alphasift_unavailable_exception(
            "AlphaSift 适配层 get_status 返回结构非法，请检查适配层版本。",
            diagnostics=diagnostics,
        ) from exc
    return result


def _is_expected_alphasift_missing(exc: ModuleNotFoundError) -> bool:
    return getattr(exc, "name", None) in ALPHASIFT_EXPECTED_MISSING_MODULES


def _alphasift_unavailable_exception(
    message: str,
    *,
    diagnostics: Optional[Dict[str, str]] = None,
) -> HTTPException:
    detail: Dict[str, Any] = {"error": "alphasift_unavailable", "message": message}
    if diagnostics:
        detail["diagnostics"] = diagnostics
    return HTTPException(status_code=424, detail=detail)


def _log_unexpected_alphasift_exception(stage: str, exc: BaseException) -> Dict[str, str]:
    logger.warning("Unexpected AlphaSift %s failure: %s", stage, exc, exc_info=exc.__traceback__ is not None)
    return {
        "reason": "unexpected_exception",
        "stage": stage,
        "error_type": exc.__class__.__name__,
    }


def _extract_alphasift_diagnostics(exc: HTTPException) -> Optional[Dict[str, str]]:
    detail = exc.detail if isinstance(exc.detail, dict) else {}
    diagnostics = detail.get("diagnostics")
    if not isinstance(diagnostics, dict):
        return None
    return {str(key): str(value) for key, value in diagnostics.items()}


def _list_strategies() -> List[Dict[str, Any]]:
    adapter = _get_dsa_adapter()
    list_strategies = _get_adapter_callable(adapter, "list_strategies", "list_strategies() 不可调用。")
    raw = _to_plain(list_strategies())
    if not isinstance(raw, list):
        raise HTTPException(
            status_code=424,
            detail={"error": "alphasift_invalid_result", "message": "AlphaSift list_strategies 返回非列表。"},
        )

    normalized: List[Dict[str, Any]] = []
    for item in raw:
        strategy = _normalize_strategy(item)
        if not strategy.get("id"):
            continue
        normalized.append(strategy)
    return normalized


def _normalize_strategy(raw: Any) -> Dict[str, Any]:
    item = _to_plain(raw)
    if isinstance(item, str):
        return _strategy_model(id=item, name=item, title=item)
    if not isinstance(item, dict):
        value = str(item)
        return _strategy_model(id=value, name=value, title=value)

    tags = item.get("tags") if isinstance(item.get("tags"), list) else []
    market_scope = item.get("market_scope") or item.get("marketScope") or []
    if not isinstance(market_scope, list):
        market_scope = [str(market_scope)] if market_scope else []

    strategy_id = str(
        item.get("id")
        or item.get("strategy")
        or item.get("strategy_id")
        or item.get("name")
        or "",
    )
    name = str(item.get("name") or item.get("title") or strategy_id)
    category = str(item.get("category") or item.get("tag") or "")
    return _strategy_model(
        id=strategy_id,
        name=name,
        title=str(item.get("title") or name),
        description=str(item.get("description") or ""),
        category=category,
        tag=str(item.get("tag") or category),
        tags=[str(tag) for tag in tags],
        market_scope=[str(market) for market in market_scope],
        market=str(item.get("market") or item.get("market_id") or ""),
    )


def _strategy_model(**kwargs: Any) -> Dict[str, Any]:
    normalized = AlphaSiftStrategyResponse(**kwargs)
    try:
        return normalized.model_dump()
    except AttributeError:
        return normalized.dict()


def _ensure_supported_strategy(strategy: str) -> None:
    strategies = _list_strategies()
    if not strategies:
        return

    ids = {item.get("id") for item in strategies if item.get("id")}
    if strategy in ids:
        return

    # 兼容“策略列表为空时手动输入”以及“用户手动覆盖策略参数”场景，
    # 策略由适配层进行最终校验，因此在列表外仍保持透传。


def _call_alphasift_screen(screen: Any, strategy: str, market: str, max_results: int) -> Any:
    signature = inspect.signature(screen)
    params = signature.parameters
    supports_var_kwargs = any(parameter.kind == inspect.Parameter.VAR_KEYWORD for parameter in params.values())
    positional_params = [
        parameter
        for parameter in params.values()
        if parameter.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
    ]
    supports_var_positional = any(parameter.kind == inspect.Parameter.VAR_POSITIONAL for parameter in params.values())

    supports_max_results = "max_results" in params or supports_var_kwargs
    supports_max_output = "max_output" in params or supports_var_kwargs
    supports_use_llm = "use_llm" in params or supports_var_kwargs

    kwargs: Dict[str, Any] = {"market": market}
    if supports_max_results:
        kwargs["max_results"] = max_results
    elif supports_max_output:
        kwargs["max_output"] = max_results
    else:
        kwargs["max_results"] = max_results

    if supports_use_llm:
        kwargs["use_llm"] = True

    try:
        return screen(strategy, **kwargs)
    except TypeError as exc:
        message = str(exc)
        signature_mismatch = ("keyword" in message and "argument" in message) or (
            "positional" in message and "given" in message
        )
        if not signature_mismatch:
            raise
        if not (supports_var_kwargs or supports_var_positional or len(positional_params) >= 3):
            raise
        return screen(strategy, market, max_results)


def _ensure_supported_market(market: str) -> None:
    status = _call_alphasift_status()
    supported_markets = status.get("supported_markets") or status.get("markets") or status.get("market")
    if not supported_markets:
        return

    normalized: List[Any]
    if isinstance(supported_markets, str):
        normalized = [supported_markets]
    elif isinstance(supported_markets, (list, tuple, set)):
        normalized = list(supported_markets)
    else:
        normalized = []

    if market not in normalized:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "alphasift_invalid_market",
                "message": (
                    f"市场 {market} 不在 AlphaSift 适配层支持范围内"
                    f"（支持市场：{', '.join(map(str, normalized)) or '未知'}）。"
                ),
            },
        )


def _normalize_candidates(raw: Any) -> List[Dict[str, Any]]:
    data = _to_plain(raw)
    items = data
    if isinstance(data, dict):
        for key in ("candidates", "picks", "items", "results", "stocks"):
            if isinstance(data.get(key), list):
                items = data[key]
                break
    if not isinstance(items, list):
        return []
    return [_normalize_candidate(item, index + 1) for index, item in enumerate(items)]


def _normalize_candidate(raw: Any, rank: int) -> Dict[str, Any]:
    item = _remove_non_finite_json_values(_to_plain(raw))
    if not isinstance(item, dict):
        item = {"code": str(item)}
    source = item.get("raw") if isinstance(item.get("raw"), dict) else item
    return {
        "rank": item.get("rank") or source.get("rank") or rank,
        "code": item.get("code") or source.get("code") or item.get("symbol") or source.get("symbol") or item.get("stock_code") or source.get("stock_code") or "",
        "name": item.get("name") or source.get("name") or item.get("stock_name") or source.get("stock_name") or "",
        "score": _first_present(item, source, "score", "final_score"),
        "screen_score": _first_present(item, source, "screen_score"),
        "reason": item.get("reason") or source.get("reason") or source.get("ranking_reason") or source.get("risk_summary") or item.get("summary") or _build_candidate_reason(source),
        "risk_level": item.get("risk_level") or source.get("risk_level") or "",
        "risk_flags": item.get("risk_flags") or source.get("risk_flags") or [],
        "llm_score": _first_present(item, source, "llm_score"),
        "llm_confidence": _first_present(item, source, "llm_confidence"),
        "llm_sector": item.get("llm_sector") or source.get("llm_sector") or "",
        "llm_theme": item.get("llm_theme") or source.get("llm_theme") or "",
        "llm_tags": item.get("llm_tags") or source.get("llm_tags") or [],
        "llm_thesis": item.get("llm_thesis") or source.get("llm_thesis") or "",
        "llm_catalysts": item.get("llm_catalysts") or source.get("llm_catalysts") or [],
        "llm_risks": item.get("llm_risks") or source.get("llm_risks") or [],
        "llm_watch_items": item.get("llm_watch_items") or source.get("llm_watch_items") or [],
        "llm_invalidators": item.get("llm_invalidators") or source.get("llm_invalidators") or [],
        "llm_style_fit": item.get("llm_style_fit") or source.get("llm_style_fit") or "",
        "price": _first_present(item, source, "price"),
        "change_pct": _first_present(item, source, "change_pct"),
        "amount": _first_present(item, source, "amount"),
        "industry": item.get("industry") or source.get("industry") or "",
        "factor_scores": item.get("factor_scores") or source.get("factor_scores") or {},
        "post_analysis_summaries": item.get("post_analysis_summaries") or source.get("post_analysis_summaries") or {},
        "post_analysis_tags": item.get("post_analysis_tags") or source.get("post_analysis_tags") or [],
        "raw": source,
    }


def _first_present(primary: Dict[str, Any], source: Dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if primary.get(key) is not None:
            return primary.get(key)
        if source.get(key) is not None:
            return source.get(key)
    return None


def _build_candidate_reason(item: Dict[str, Any]) -> str:
    summaries = item.get("post_analysis_summaries")
    if isinstance(summaries, dict):
        summary = next((str(value) for value in summaries.values() if value), "")
        if summary:
            return summary

    factors = item.get("factor_scores")
    parts: List[str] = []
    if isinstance(factors, dict) and factors:
        top_factors = sorted(
            ((key, value) for key, value in factors.items() if isinstance(value, (int, float))),
            key=lambda pair: pair[1],
            reverse=True,
        )[:3]
        if top_factors:
            factor_text = "、".join(f"{key} {value:.1f}" for key, value in top_factors)
            parts.append(f"主要因子：{factor_text}")
    if item.get("industry"):
        parts.append(f"行业：{item['industry']}")
    if item.get("risk_level"):
        parts.append(f"风险等级：{item['risk_level']}")
    return "；".join(parts)


def _to_plain(value: Any) -> Any:
    if is_dataclass(value):
        return asdict(value)
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if hasattr(value, "dict") and callable(value.dict):
        return value.dict()
    if isinstance(value, list):
        return [_to_plain(item) for item in value]
    return value


def _remove_non_finite_json_values(value: Any) -> Any:
    if isinstance(value, list):
        return [_remove_non_finite_json_values(item) for item in value]
    if isinstance(value, tuple):
        return [_remove_non_finite_json_values(item) for item in value]
    if isinstance(value, dict):
        return {key: _remove_non_finite_json_values(item) for key, item in value.items()}
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    return value


def _build_install_response(already_installed: bool, install_spec_is_default: bool) -> Dict[str, Any]:
    return {
        "installed": True,
        "already_installed": already_installed,
        "install_spec_is_default": install_spec_is_default,
    }


def _is_default_alphasift_install_spec(install_spec: str) -> bool:
    return (install_spec or "").strip() == DEFAULT_ALPHASIFT_INSTALL_SPEC
