# -*- coding: utf-8 -*-
"""
===================================
A股自选股智能分析系统 - 分析服务层
===================================

职责：
1. 封装核心分析逻辑，支持多调用方（CLI、WebUI、Bot）
2. 提供清晰的API接口，不依赖于命令行参数
3. 支持依赖注入，便于测试和扩展
4. 统一管理分析流程和配置
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Sequence, Union

if TYPE_CHECKING:
    from src.analyzer import AnalysisResult
    from src.config import Config
    from src.core.pipeline import StockAnalysisPipeline
    from src.notification import NotificationService


class StockAnalysisMode(str, Enum):
    """Controls which expensive capabilities a service call may use."""

    CHECK = "check"
    DATA = "data"
    FULL = "full"

    @classmethod
    def from_value(cls, value: Union["StockAnalysisMode", str]) -> "StockAnalysisMode":
        if isinstance(value, cls):
            return value

        normalized = str(value or "").strip().lower().replace("_", "-")
        aliases = {
            "check": cls.CHECK,
            "health": cls.CHECK,
            "preflight": cls.CHECK,
            "data": cls.DATA,
            "fetch": cls.DATA,
            "fetch-only": cls.DATA,
            "dry-run": cls.DATA,
            "full": cls.FULL,
            "analysis": cls.FULL,
            "ai": cls.FULL,
        }
        try:
            return aliases[normalized]
        except KeyError as exc:
            supported = ", ".join(mode.value for mode in cls)
            raise ValueError(f"不支持的分析模式 {value!r}，可选值: {supported}") from exc


@dataclass
class StockAnalysisRunResult:
    """Structured outcome shared by check, data-only, and full analysis modes."""

    stock_code: str
    mode: StockAnalysisMode
    success: bool
    query_id: str
    analysis: Optional["AnalysisResult"] = None
    error: Optional[str] = None
    network_allowed: bool = False
    llm_allowed: bool = False
    notification_allowed: bool = False
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self, include_analysis: bool = True) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "stock_code": self.stock_code,
            "mode": self.mode.value,
            "success": self.success,
            "query_id": self.query_id,
            "error": self.error,
            "capabilities": {
                "network": self.network_allowed,
                "llm": self.llm_allowed,
                "notification": self.notification_allowed,
            },
            "details": dict(self.details),
        }
        if include_analysis:
            if self.analysis is None:
                payload["analysis"] = None
            elif hasattr(self.analysis, "to_dict"):
                payload["analysis"] = self.analysis.to_dict()
            else:
                payload["analysis"] = self.analysis
        return payload


def _resolve_config(config: Optional["Config"]) -> "Config":
    if config is not None:
        return config

    from src.config import get_config

    return get_config()


def _build_pipeline(config: "Config", query_id: str) -> "StockAnalysisPipeline":
    from src.core.pipeline import StockAnalysisPipeline

    return StockAnalysisPipeline(
        config=config,
        query_id=query_id,
        query_source="cli",
    )


def _module_available(module_name: str) -> bool:
    if module_name in sys.modules:
        return True
    try:
        return importlib.util.find_spec(module_name) is not None
    except (AttributeError, ImportError, ValueError):
        return False


def _build_readiness_details(config: "Config") -> Dict[str, Any]:
    pipeline_available = _module_available("src.core.pipeline")
    pandas_available = _module_available("pandas")
    litellm_available = _module_available("litellm")
    data_mode_ready = pipeline_available and pandas_available
    full_analysis_ready = data_mode_ready and litellm_available
    return {
        "config_loaded": True,
        "pipeline_module_available": pipeline_available,
        "market_data_runtime_available": pandas_available,
        "llm_runtime_available": litellm_available,
        "data_mode_ready": data_mode_ready,
        "full_analysis_ready": full_analysis_ready,
        "generation_backend": getattr(config, "generation_backend", None),
        "realtime_source_priority": getattr(config, "realtime_source_priority", None),
        "max_workers": getattr(config, "max_workers", None),
    }


def run_stock_analysis(
    stock_code: str,
    *,
    mode: Union[StockAnalysisMode, str] = StockAnalysisMode.CHECK,
    config: Optional["Config"] = None,
    full_report: bool = False,
    notifier: Optional["NotificationService"] = None,
    force_refresh: bool = False,
) -> StockAnalysisRunResult:
    """Run one stock with explicit network, LLM, and notification boundaries.

    ``check`` only validates local readiness. ``data`` fetches and stores market
    data without analysis or notification. ``full`` preserves the existing AI
    analysis flow and only sends a notification when a notifier is provided.
    """
    normalized_mode = StockAnalysisMode.from_value(mode)
    code = str(stock_code or "").strip()
    query_id = uuid.uuid4().hex

    if not code:
        return StockAnalysisRunResult(
            stock_code=code,
            mode=normalized_mode,
            success=False,
            query_id=query_id,
            error="股票代码不能为空",
        )

    try:
        resolved_config = _resolve_config(config)
    except Exception as exc:
        return StockAnalysisRunResult(
            stock_code=code,
            mode=normalized_mode,
            success=False,
            query_id=query_id,
            error=f"配置加载失败: {exc}",
        )

    if normalized_mode is StockAnalysisMode.CHECK:
        details = _build_readiness_details(resolved_config)
        success = bool(details["full_analysis_ready"])
        return StockAnalysisRunResult(
            stock_code=code,
            mode=normalized_mode,
            success=success,
            query_id=query_id,
            details=details,
            error=None if success else "本地运行环境不完整",
        )

    try:
        pipeline = _build_pipeline(resolved_config, query_id)
    except Exception as exc:
        return StockAnalysisRunResult(
            stock_code=code,
            mode=normalized_mode,
            success=False,
            query_id=query_id,
            network_allowed=True,
            llm_allowed=normalized_mode is StockAnalysisMode.FULL,
            notification_allowed=normalized_mode is StockAnalysisMode.FULL and notifier is not None,
            error=f"分析流水线初始化失败: {exc}",
        )

    if normalized_mode is StockAnalysisMode.DATA:
        success, error = pipeline.fetch_and_save_stock_data(
            code,
            force_refresh=force_refresh,
        )
        return StockAnalysisRunResult(
            stock_code=code,
            mode=normalized_mode,
            success=success,
            query_id=query_id,
            network_allowed=True,
            error=error,
            details={"force_refresh": force_refresh, "data_ready": success},
        )

    if notifier is not None:
        pipeline.notifier = notifier

    from src.enums import ReportType

    report_type = ReportType.FULL if full_report else ReportType.SIMPLE
    result = pipeline.process_single_stock(
        code=code,
        skip_analysis=False,
        single_stock_notify=notifier is not None,
        report_type=report_type,
    )
    success = result is not None and bool(getattr(result, "success", True))
    error = None
    if result is None:
        error = "分析未返回结果"
    elif not success:
        error = getattr(result, "error_message", None) or "分析未成功完成"

    return StockAnalysisRunResult(
        stock_code=code,
        mode=normalized_mode,
        success=success,
        query_id=query_id,
        analysis=result,
        error=error,
        network_allowed=True,
        llm_allowed=True,
        notification_allowed=notifier is not None,
        details={"report_type": report_type.value},
    )


def run_stock_analyses(
    stock_codes: Sequence[str],
    *,
    mode: Union[StockAnalysisMode, str] = StockAnalysisMode.CHECK,
    config: Optional["Config"] = None,
    full_report: bool = False,
    notifier: Optional["NotificationService"] = None,
    force_refresh: bool = False,
) -> List[StockAnalysisRunResult]:
    """Run multiple stocks while retaining a result for every requested code."""
    if not stock_codes:
        return []

    return [
        run_stock_analysis(
            stock_code,
            mode=mode,
            config=config,
            full_report=full_report,
            notifier=notifier,
            force_refresh=force_refresh,
        )
        for stock_code in stock_codes
    ]


def analyze_stock(
    stock_code: str,
    config: Optional["Config"] = None,
    full_report: bool = False,
    notifier: Optional["NotificationService"] = None,
) -> Optional["AnalysisResult"]:
    """
    分析单只股票

    Args:
        stock_code: 股票代码
        config: 配置对象（可选，默认使用单例）
        full_report: 是否生成完整报告
        notifier: 通知服务（可选）

    Returns:
        分析结果对象
    """
    outcome = run_stock_analysis(
        stock_code,
        mode=StockAnalysisMode.FULL,
        config=config,
        full_report=full_report,
        notifier=notifier,
    )
    return outcome.analysis


def analyze_stocks(
    stock_codes: List[str],
    config: Optional["Config"] = None,
    full_report: bool = False,
    notifier: Optional["NotificationService"] = None,
) -> List["AnalysisResult"]:
    """
    分析多只股票

    Args:
        stock_codes: 股票代码列表
        config: 配置对象（可选，默认使用单例）
        full_report: 是否生成完整报告
        notifier: 通知服务（可选）

    Returns:
        分析结果列表
    """
    if config is None:
        config = _resolve_config(config)

    results = []
    for stock_code in stock_codes:
        result = analyze_stock(stock_code, config, full_report, notifier)
        if result:
            results.append(result)

    return results


def perform_market_review(
    config: Optional["Config"] = None,
    notifier: Optional["NotificationService"] = None,
) -> Optional[str]:
    """
    执行大盘复盘

    Args:
        config: 配置对象（可选，默认使用单例）
        notifier: 通知服务（可选）

    Returns:
        复盘报告内容
    """
    config = _resolve_config(config)

    # 创建分析流水线以获取analyzer和search_service
    pipeline = _build_pipeline(config, uuid.uuid4().hex)

    # 使用提供的通知服务或创建新的
    review_notifier = notifier or pipeline.notifier

    from src.core.market_review import run_market_review

    # 调用大盘复盘函数
    return run_market_review(
        notifier=review_notifier,
        analyzer=pipeline.analyzer,
        search_service=pipeline.search_service,
        config=config,
        trigger_source="service",
    )


def main(argv: Optional[Sequence[str]] = None) -> int:
    """File-based CLI that avoids interactive-stdin multiprocessing issues."""
    parser = argparse.ArgumentParser(description="按成本边界运行股票分析")
    parser.add_argument("stock_codes", nargs="+", help="股票代码，例如 600519 AAPL 00700.HK")
    parser.add_argument(
        "--mode",
        choices=[mode.value for mode in StockAnalysisMode],
        default=StockAnalysisMode.CHECK.value,
        help="check=本地体检，data=仅拉取行情，full=完整 AI 分析",
    )
    parser.add_argument("--full-report", action="store_true", help="full 模式生成完整报告")
    parser.add_argument("--force-refresh", action="store_true", help="data 模式忽略本地行情缓存")
    parser.add_argument("--notify", action="store_true", help="full 模式启用已配置通知渠道")
    args = parser.parse_args(argv)

    mode = StockAnalysisMode.from_value(args.mode)
    if args.notify and mode is not StockAnalysisMode.FULL:
        parser.error("--notify 只能与 --mode full 一起使用")
    if args.full_report and mode is not StockAnalysisMode.FULL:
        parser.error("--full-report 只能与 --mode full 一起使用")
    if args.force_refresh and mode is not StockAnalysisMode.DATA:
        parser.error("--force-refresh 只能与 --mode data 一起使用")

    notifier = None
    if args.notify:
        from src.notification import NotificationService

        notifier = NotificationService()

    outcomes = run_stock_analyses(
        args.stock_codes,
        mode=mode,
        full_report=args.full_report,
        notifier=notifier,
        force_refresh=args.force_refresh,
    )
    include_analysis = mode is StockAnalysisMode.FULL
    print(
        json.dumps(
            [outcome.to_dict(include_analysis=include_analysis) for outcome in outcomes],
            ensure_ascii=False,
            indent=2,
            default=str,
        )
    )
    return 0 if all(outcome.success for outcome in outcomes) else 1


if __name__ == "__main__":
    raise SystemExit(main())
