# -*- coding: utf-8 -*-
"""
===================================
平台适配器基类
===================================

定义平台适配器的抽象基类，各平台必须继承此类。
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, Tuple

from bot.models import BotMessage, BotResponse, WebhookResponse


class BotPlatform(ABC):
    """
    平台适配器抽象基类
    
    负责：
    1. 验证 Webhook 请求签名
    2. 解析平台消息为统一格式
    3. 将响应转换为平台格式
    
    使用示例：
        class MyPlatform(BotPlatform):
            @property
            def platform_name(self) -> str:
                return "myplatform"
            
            def verify_request(self, headers, body) -> bool:
                # 验证签名逻辑
                return True
            
            def parse_message(self, data) -> Optional[BotMessage]:
                # 解析消息逻辑
                return BotMessage(...)
            
            def format_response(self, response, message) -> WebhookResponse:
                # 格式化响应逻辑
                return WebhookResponse.success({"text": response.text})
    """
    
    @property
    @abstractmethod
    def platform_name(self) -> str:
        """
        平台标识名称
        
        用于路由匹配和日志标识，如 "feishu", "dingtalk"
        """
        pass
    
    @abstractmethod
    def verify_request(self, headers: Dict[str, str], body: bytes) -> bool:
        """
        验证请求签名
        
        各平台有不同的签名验证机制，需要单独实现。
        
        Args:
            headers: HTTP 请求头
            body: 请求体原始字节
            
        Returns:
            签名是否有效
        """
        pass
    
    @abstractmethod
    def parse_message(self, data: Dict[str, Any]) -> Optional[BotMessage]:
        """
        解析平台消息为统一格式
        
        将平台特定的消息格式转换为 BotMessage。
        如果不是需要处理的消息类型（如事件回调），返回 None。
        
        Args:
            data: 解析后的 JSON 数据
            
        Returns:
            BotMessage 对象，或 None（不需要处理）
        """
        pass
    
    @abstractmethod
    def format_response(
        self, 
        response: BotResponse, 
        message: BotMessage
    ) -> WebhookResponse:
        """
        将统一响应转换为平台格式
        
        Args:
            response: 统一响应对象
            message: 原始消息对象（用于获取回复目标等信息）
            
        Returns:
            WebhookResponse 对象
        """
        pass
    
    def handle_challenge(self, data: Dict[str, Any]) -> Optional[WebhookResponse]:
        """
        处理平台验证请求
        
        部分平台在配置 Webhook 时会发送验证请求，需要返回特定响应。
        子类可重写此方法。
        
        Args:
            data: 请求数据
            
        Returns:
            验证响应，或 None（不是验证请求）
        """
        return None
    
    def handle_webhook(
        self, 
        headers: Dict[str, str], 
        body: bytes,
        data: Dict[str, Any]
    ) -> Tuple[Optional[BotMessage], Optional[WebhookResponse]]:
        """
        处理 Webhook 请求
        
        这是主入口方法，协调验证、解析等流程。
        
        Args:
            headers: HTTP 请求头
            body: 请求体原始字节
            data: 解析后的 JSON 数据
            
        Returns:
            (BotMessage, WebhookResponse) 元组
            - 如果是验证请求：(None, challenge_response)
            - 如果是普通消息：(message, None) - 响应将在命令处理后生成
            - 如果验证失败或无需处理：(None, error_response 或 None)
        """
        # 1. 检查是否是验证请求
        challenge_response = self.handle_challenge(data)
        if challenge_response:
            return None, challenge_response
        
        # 2. 验证请求签名
        if not self.verify_request(headers, body):
            return None, WebhookResponse.error("Invalid signature", 403)
        
        # 3. 解析消息
        message = self.parse_message(data)
        
        return message, None
