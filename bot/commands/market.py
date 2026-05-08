# -*- coding: utf-8 -*-
"""
===================================
大盘复盘命令
===================================

执行大盘复盘分析，生成市场概览报告。
"""

import logging
import threading
from typing import List

from bot.commands.base import BotCommand
from bot.models import BotMessage, BotResponse

logger = logging.getLogger(__name__)


class MarketCommand(BotCommand):
    """
    大盘复盘命令
    
    执行大盘复盘分析，包括：
    - 主要指数表现
    - 板块热点
    - 市场情绪
    - 后市展望
    
    用法：
        /market - 执行大盘复盘
    """

    @property
    def name(self) -> str:
        return "market"

    @property
    def aliases(self) -> List[str]:
        return ["m", "大盘", "复盘", "行情"]

    @property
    def description(self) -> str:
        return "大盘复盘分析"

    @property
    def usage(self) -> str:
        return "/market"

    def execute(self, message: BotMessage, args: List[str]) -> BotResponse:
        """执行大盘复盘命令"""
        logger.info(f"[MarketCommand] 开始大盘复盘分析")

        # 在后台线程中执行复盘（避免阻塞）
        thread = threading.Thread(
            target=self._run_market_review,
            args=(message,),
            daemon=True
        )
        thread.start()

        return BotResponse.markdown_response(
            "✅ **大盘复盘任务已启动**\n\n"
            "正在分析：\n"
            "• 主要指数表现\n"
            "• 板块热点分析\n"
            "• 市场情绪判断\n"
            "• 后市展望\n\n"
            "分析完成后将自动推送结果。"
        )

    def _run_market_review(self, message: BotMessage) -> None:
        """后台执行大盘复盘"""
        try:
            from src.config import get_config
            from src.notification import NotificationService
            from src.core.market_review import run_market_review
            from src.search_service import SearchService
            from src.analyzer import GeminiAnalyzer

            config = get_config()
            notifier = NotificationService(source_message=message)

            # 交易日过滤：与 main.py 行为一致，避免在所有相关市场休市时仍调用复盘 / 推送
            override_region: "str | None" = None
            if getattr(config, "trading_day_check_enabled", True):
                try:
                    from src.core.trading_calendar import (
                        get_open_markets_today,
                        compute_effective_region,
                    )

                    open_markets = get_open_markets_today()
                    override_region = compute_effective_region(
                        getattr(config, "market_review_region", "cn") or "cn",
                        open_markets,
                    )
                except Exception as calendar_err:
                    logger.warning(
                        "[MarketCommand] 交易日过滤 fail-open: %s", calendar_err
                    )
                    override_region = None

                if override_region == "":
                    logger.info("[MarketCommand] 今日相关市场休市，跳过大盘复盘")
                    if notifier.is_available():
                        notifier.send(
                            "🎯 大盘复盘\n\n今日相关市场休市，已跳过大盘复盘。",
                            email_send_to_all=True,
                        )
                    return

            # 初始化搜索服务
            search_service = None
            if config.has_search_capability_enabled():
                search_service = SearchService(
                    anspire_keys=config.anspire_api_keys,
                    bocha_keys=config.bocha_api_keys,
                    tavily_keys=config.tavily_api_keys,
                    brave_keys=config.brave_api_keys,
                    serpapi_keys=config.serpapi_keys,
                    minimax_keys=config.minimax_api_keys,
                    searxng_base_urls=config.searxng_base_urls,
                    searxng_public_instances_enabled=config.searxng_public_instances_enabled,
                    news_max_age_days=config.news_max_age_days,
                )

            # 初始化 AI 分析器
            analyzer = None
            if config.gemini_api_key or config.openai_api_key:
                analyzer = GeminiAnalyzer()

            # 委托给 run_market_review，正确处理 both / 逗号分隔等多市场路由
            review_report = run_market_review(
                notifier=notifier,
                analyzer=analyzer,
                search_service=search_service,
                send_notification=True,
                override_region=override_region,
            )

            if review_report:
                logger.info("[MarketCommand] 大盘复盘完成并已推送")
            else:
                logger.warning("[MarketCommand] 大盘复盘返回空结果")

        except Exception as e:
            logger.error(f"[MarketCommand] 大盘复盘失败: {e}")
            logger.exception(e)
