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

import logging
import uuid
from typing import List, Optional

from src.analyzer import AnalysisResult
from src.core.market_review import run_market_review
from src.core.market_review_lock import (
    release_market_review_lock,
    try_acquire_market_review_lock,
)
from src.core.pipeline import StockAnalysisPipeline
from src.config import Config, get_config
from src.enums import ReportType
from src.notification import NotificationService

logger = logging.getLogger(__name__)


def analyze_stock(
    stock_code: str,
    config: Config = None,
    full_report: bool = False,
    notifier: Optional[NotificationService] = None,
) -> Optional[AnalysisResult]:
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
    if config is None:
        config = get_config()

    # 创建分析流水线
    pipeline = StockAnalysisPipeline(
        config=config,
        query_id=uuid.uuid4().hex,
        query_source="cli"
    )

    # 使用通知服务（如果提供）
    if notifier:
        pipeline.notifier = notifier

    # 根据full_report参数设置报告类型
    report_type = ReportType.FULL if full_report else ReportType.SIMPLE

    # 运行单只股票分析
    result = pipeline.process_single_stock(
        code=stock_code,
        skip_analysis=False,
        single_stock_notify=notifier is not None,
        report_type=report_type,
    )

    return result


def analyze_stocks(
    stock_codes: List[str],
    config: Config = None,
    full_report: bool = False,
    notifier: Optional[NotificationService] = None,
) -> List[AnalysisResult]:
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
        config = get_config()

    results = []
    for stock_code in stock_codes:
        result = analyze_stock(stock_code, config, full_report, notifier)
        if result:
            results.append(result)

    return results


def perform_market_review(
    config: Config = None,
    notifier: Optional[NotificationService] = None,
    send_notification: bool = True,
) -> Optional[str]:
    """
    执行大盘复盘

    Acquires the same-host market-review lock used by Web/API, CLI, and Bot.
    Returns None when another review is already running on this host/data path.

    Args:
        config: 配置对象（可选，默认使用单例）
        notifier: 通知服务（可选）
        send_notification: 是否向外部通知渠道推送（默认 True，保持既有行为；
            对话/插件场景应显式传 False，除非用户要求推送）

    Returns:
        复盘报告内容；锁已被占用或复盘失败时为 None
    """
    if config is None:
        config = get_config()

    lock_token = try_acquire_market_review_lock(config)
    if lock_token is None:
        logger.warning("Market review is already running, skipping this market review")
        return None

    try:
        # 创建分析流水线以获取analyzer和search_service
        pipeline = StockAnalysisPipeline(
            config=config,
            query_id=uuid.uuid4().hex,
            query_source="cli",
        )

        # 使用提供的通知服务或创建新的
        review_notifier = notifier or pipeline.notifier

        # 调用大盘复盘函数
        return run_market_review(
            notifier=review_notifier,
            analyzer=pipeline.analyzer,
            search_service=pipeline.search_service,
            config=config,
            send_notification=send_notification,
            trigger_source="service",
        )
    finally:
        release_market_review_lock(lock_token)
