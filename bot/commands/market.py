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
            from src.market_analyzer import MarketAnalyzer
            from src.search_service import SearchService
            from src.analyzer import GeminiAnalyzer

            config = get_config()
            notifier = NotificationService(source_message=message)

            # 初始化搜索服务
            search_service = None
            if config.bocha_api_keys or config.tavily_api_keys or config.brave_api_keys or config.serpapi_keys:
                search_service = SearchService(
                    bocha_keys=config.bocha_api_keys,
                    tavily_keys=config.tavily_api_keys,
                    brave_keys=config.brave_api_keys,
                    serpapi_keys=config.serpapi_keys,
                    news_max_age_days=config.news_max_age_days,
                )

            # 初始化 AI 分析器
            analyzer = None
            if config.gemini_api_key or config.openai_api_key:
                analyzer = GeminiAnalyzer()

            # 读取配置中的市场区域，与定时任务/CLI 保持一致
            region = getattr(config, 'market_review_region', 'cn')

            # 执行复盘
            market_analyzer = MarketAnalyzer(
                search_service=search_service,
                analyzer=analyzer,
                region=region,
            )

            review_report = market_analyzer.run_daily_review()

            if review_report:
                # 推送结果
                report_content = f"🎯 **大盘复盘**\n\n{review_report}"
                notifier.send(report_content, email_send_to_all=True)
                logger.info("[MarketCommand] 大盘复盘完成并已推送")
            else:
                logger.warning("[MarketCommand] 大盘复盘返回空结果")

        except Exception as e:
            logger.error(f"[MarketCommand] 大盘复盘失败: {e}")
            logger.exception(e)
