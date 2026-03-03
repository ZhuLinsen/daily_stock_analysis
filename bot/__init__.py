# -*- coding: utf-8 -*-
"""
===================================
机器人命令触发系统
===================================

通过 @机器人 或发送命令触发股票分析等功能。
支持飞书、钉钉、企业微信、Telegram 等多平台。

模块结构：
- models.py: 统一的消息/响应模型
- dispatcher.py: 命令分发器
- commands/: 命令处理器
- platforms/: 平台适配器
- handler.py: Webhook 处理器

使用方式：
1. 配置环境变量（各平台的 Token 等）
2. 启动 WebUI 服务
3. 在各平台配置 Webhook URL：
   - 飞书: http://your-server/bot/feishu
   - 钉钉: http://your-server/bot/dingtalk
   - 企业微信: http://your-server/bot/wecom
   - Telegram: http://your-server/bot/telegram

支持的命令：
- /analyze <股票代码>  - 分析指定股票
- /market             - 大盘复盘
- /batch              - 批量分析自选股
- /help               - 显示帮助
- /status             - 系统状态
"""

from bot.models import BotMessage, BotResponse, ChatType, WebhookResponse
from bot.dispatcher import CommandDispatcher, get_dispatcher

__all__ = [
    'BotMessage',
    'BotResponse',
    'ChatType',
    'WebhookResponse',
    'CommandDispatcher',
    'get_dispatcher',
]
