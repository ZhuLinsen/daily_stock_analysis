# -*- coding: utf-8 -*-
"""
===================================
Bot Webhook 处理器
===================================

处理各平台的 Webhook 回调，分发到命令处理器。
"""

import json
import logging
from typing import Dict, Any, Optional, TYPE_CHECKING

from bot.models import WebhookResponse
from bot.dispatcher import get_dispatcher
from bot.platforms import ALL_PLATFORMS

if TYPE_CHECKING:
    from bot.platforms.base import BotPlatform

logger = logging.getLogger(__name__)

# 平台实例缓存
_platform_instances: Dict[str, 'BotPlatform'] = {}


def get_platform(platform_name: str) -> Optional['BotPlatform']:
    """
    获取平台适配器实例
    
    使用缓存避免重复创建。
    
    Args:
        platform_name: 平台名称
        
    Returns:
        平台适配器实例，或 None
    """
    if platform_name not in _platform_instances:
        platform_class = ALL_PLATFORMS.get(platform_name)
        if platform_class:
            _platform_instances[platform_name] = platform_class()
        else:
            logger.warning(f"[BotHandler] 未知平台: {platform_name}")
            return None
    
    return _platform_instances[platform_name]


def handle_webhook(
    platform_name: str,
    headers: Dict[str, str],
    body: bytes,
    query_params: Optional[Dict[str, list]] = None
) -> WebhookResponse:
    """
    处理 Webhook 请求
    
    这是所有平台 Webhook 的统一入口。
    
    Args:
        platform_name: 平台名称 (feishu, dingtalk, wecom, telegram)
        headers: HTTP 请求头
        body: 请求体原始字节
        query_params: URL 查询参数（用于某些平台的验证）
        
    Returns:
        WebhookResponse 响应对象
    """
    logger.info(f"[BotHandler] 收到 {platform_name} Webhook 请求")
    
    # 检查机器人功能是否启用
    from src.config import get_config
    config = get_config()
    
    if not getattr(config, 'bot_enabled', True):
        logger.info("[BotHandler] 机器人功能未启用")
        return WebhookResponse.success()
    
    # 获取平台适配器
    platform = get_platform(platform_name)
    if not platform:
        return WebhookResponse.error(f"Unknown platform: {platform_name}", 400)
    
    # 解析 JSON 数据
    try:
        data = json.loads(body.decode('utf-8')) if body else {}
    except json.JSONDecodeError as e:
        logger.error(f"[BotHandler] JSON 解析失败: {e}")
        return WebhookResponse.error("Invalid JSON", 400)
    
    logger.debug(f"[BotHandler] 请求数据: {json.dumps(data, ensure_ascii=False)[:500]}")
    
    # 处理 Webhook
    message, challenge_response = platform.handle_webhook(headers, body, data)
    
    # 如果是验证请求，直接返回验证响应
    if challenge_response:
        logger.info(f"[BotHandler] 返回验证响应")
        return challenge_response
    
    # 如果没有消息需要处理，返回空响应
    if not message:
        logger.debug("[BotHandler] 无需处理的消息")
        return WebhookResponse.success()
    
    logger.info(f"[BotHandler] 解析到消息: user={message.user_name}, content={message.content[:50]}")
    
    # 分发到命令处理器
    dispatcher = get_dispatcher()
    response = dispatcher.dispatch(message)
    
    # 格式化响应
    if response.text:
        webhook_response = platform.format_response(response, message)
        return webhook_response
    
    return WebhookResponse.success()


def handle_feishu_webhook(headers: Dict[str, str], body: bytes) -> WebhookResponse:
    """处理飞书 Webhook"""
    return handle_webhook('feishu', headers, body)


def handle_dingtalk_webhook(headers: Dict[str, str], body: bytes) -> WebhookResponse:
    """处理钉钉 Webhook"""
    return handle_webhook('dingtalk', headers, body)


def handle_wecom_webhook(headers: Dict[str, str], body: bytes) -> WebhookResponse:
    """处理企业微信 Webhook"""
    return handle_webhook('wecom', headers, body)


def handle_telegram_webhook(headers: Dict[str, str], body: bytes) -> WebhookResponse:
    """处理 Telegram Webhook"""
    return handle_webhook('telegram', headers, body)
