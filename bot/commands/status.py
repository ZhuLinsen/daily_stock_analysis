# -*- coding: utf-8 -*-
"""
===================================
状态命令
===================================

显示系统运行状态和配置信息。
"""

import platform
import sys
from datetime import datetime
from typing import List

from bot.commands.base import BotCommand
from bot.models import BotMessage, BotResponse


class StatusCommand(BotCommand):
    """
    状态命令
    
    显示系统运行状态，包括：
    - 服务状态
    - 配置信息
    - 可用功能
    """
    
    @property
    def name(self) -> str:
        return "status"
    
    @property
    def aliases(self) -> List[str]:
        return ["s", "状态", "info"]
    
    @property
    def description(self) -> str:
        return "显示系统状态"
    
    @property
    def usage(self) -> str:
        return "/status"
    
    def execute(self, message: BotMessage, args: List[str]) -> BotResponse:
        """执行状态命令"""
        from src.config import get_config
        
        config = get_config()
        
        # 收集状态信息
        status_info = self._collect_status(config)
        
        # 格式化输出
        text = self._format_status(status_info, message.platform)
        
        return BotResponse.markdown_response(text)
    
    def _collect_status(self, config) -> dict:
        """收集系统状态信息"""
        status = {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "python_version": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
            "platform": platform.system(),
            "stock_count": len(config.stock_list),
            "stock_list": config.stock_list[:5],  # 只显示前5个
        }
        
        # AI 配置状态
        status["ai_gemini"] = bool(config.gemini_api_key)
        status["ai_openai"] = bool(config.openai_api_key)
        
        # 搜索服务状态
        status["search_bocha"] = len(config.bocha_api_keys) > 0
        status["search_tavily"] = len(config.tavily_api_keys) > 0
        status["search_brave"] = len(config.brave_api_keys) > 0
        status["search_serpapi"] = len(config.serpapi_keys) > 0
        status["search_minimax"] = len(config.minimax_api_keys) > 0
        status["search_searxng"] = config.has_searxng_enabled()
        
        # 通知渠道状态
        status["notify_wechat"] = bool(config.wechat_webhook_url)
        status["notify_feishu"] = bool(config.feishu_webhook_url)
        status["notify_telegram"] = bool(config.telegram_bot_token and config.telegram_chat_id)
        status["notify_email"] = bool(config.email_sender and config.email_password)
        
        return status
    
    def _format_status(self, status: dict, platform: str) -> str:
        """格式化状态信息"""
        # 状态图标
        def icon(enabled: bool) -> str:
            return "✅" if enabled else "❌"
        
        lines = [
            "📊 **股票分析助手 - 系统状态**",
            "",
            f"🕐 时间: {status['timestamp']}",
            f"🐍 Python: {status['python_version']}",
            f"💻 平台: {status['platform']}",
            "",
            "---",
            "",
            "**📈 自选股配置**",
            f"• 股票数量: {status['stock_count']} 只",
        ]
        
        if status['stock_list']:
            stocks_preview = ", ".join(status['stock_list'])
            if status['stock_count'] > 5:
                stocks_preview += f" ... 等 {status['stock_count']} 只"
            lines.append(f"• 股票列表: {stocks_preview}")
        
        lines.extend([
            "",
            "**🤖 AI 分析服务**",
            f"• Gemini API: {icon(status['ai_gemini'])}",
            f"• OpenAI API: {icon(status['ai_openai'])}",
            "",
            "**🔍 搜索服务**",
            f"• Bocha: {icon(status['search_bocha'])}",
            f"• Tavily: {icon(status['search_tavily'])}",
            f"• Brave: {icon(status['search_brave'])}",
            f"• SerpAPI: {icon(status['search_serpapi'])}",
            f"• MiniMax: {icon(status['search_minimax'])}",
            f"• SearXNG: {icon(status['search_searxng'])}",
            "",
            "**📢 通知渠道**",
            f"• 企业微信: {icon(status['notify_wechat'])}",
            f"• 飞书: {icon(status['notify_feishu'])}",
            f"• Telegram: {icon(status['notify_telegram'])}",
            f"• 邮件: {icon(status['notify_email'])}",
        ])
        
        # AI 服务总体状态
        ai_available = status['ai_gemini'] or status['ai_openai']
        if ai_available:
            lines.extend([
                "",
                "---",
                "✅ **系统就绪，可以开始分析！**",
            ])
        else:
            lines.extend([
                "",
                "---",
                "⚠️ **AI 服务未配置，分析功能不可用**",
                "请配置 Gemini 或 OpenAI API Key",
            ])
        
        return "\n".join(lines)
