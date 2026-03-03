# -*- coding: utf-8 -*-
"""
===================================
钉钉 Stream 模式适配器
===================================

使用钉钉官方 Stream SDK 接入机器人，无需公网 IP 和 Webhook 配置。

优势：
- 不需要公网 IP 或域名
- 不需要配置 Webhook URL
- 通过 WebSocket 长连接接收消息
- 更简单的接入方式

依赖：
pip install dingtalk-stream

钉钉 Stream SDK：
https://github.com/open-dingtalk/dingtalk-stream-sdk-python
"""

import logging
import asyncio
import threading
from datetime import datetime
from typing import Optional, Callable, Any

logger = logging.getLogger(__name__)

# 尝试导入钉钉 Stream SDK
try:
    import dingtalk_stream
    from dingtalk_stream import AckMessage

    DINGTALK_STREAM_AVAILABLE = True
except ImportError:
    DINGTALK_STREAM_AVAILABLE = False
    logger.warning("[DingTalk Stream] dingtalk-stream SDK 未安装，Stream 模式不可用")
    logger.warning("[DingTalk Stream] 请运行: pip install dingtalk-stream")

from bot.models import BotMessage, BotResponse, ChatType


class DingtalkStreamHandler:
    """
    钉钉 Stream 模式消息处理器
    
    将 Stream SDK 的回调转换为统一的 BotMessage 格式，
    并调用命令分发器处理。
    """

    def __init__(self, on_message: Callable[[BotMessage], BotResponse]):
        """
        Args:
            on_message: 消息处理回调函数，接收 BotMessage 返回 BotResponse
        """
        self._on_message = on_message
        self._logger = logger

    @staticmethod
    def _truncate_log_content(text: str, max_len: int = 200) -> str:
        cleaned = text.replace("\n", " ").strip()
        if len(cleaned) > max_len:
            return f"{cleaned[:max_len]}..."
        return cleaned

    def _log_incoming_message(self, message: BotMessage) -> None:
        content = message.raw_content or message.content or ""
        summary = self._truncate_log_content(content)
        self._logger.info(
            "[DingTalk Stream] Incoming message: msg_id=%s user_id=%s chat_id=%s chat_type=%s content=%s",
            message.message_id,
            message.user_id,
            message.chat_id,
            getattr(message.chat_type, "value", message.chat_type),
            summary,
        )

    if DINGTALK_STREAM_AVAILABLE:
        class _ChatbotHandler(dingtalk_stream.ChatbotHandler):
            """内部消息处理器"""

            def __init__(self, parent: 'DingtalkStreamHandler'):
                super().__init__()
                self._parent = parent
                self.logger = logger

            async def process(self, callback: dingtalk_stream.CallbackMessage):
                """处理收到的消息"""
                try:
                    # 解析消息
                    incoming = dingtalk_stream.ChatbotMessage.from_dict(callback.data)

                    # 转换为统一格式
                    bot_message = self._parent._parse_stream_message(incoming, callback.data)

                    if bot_message:
                        self._parent._log_incoming_message(bot_message)
                        # 调用消息处理回调
                        response = self._parent._on_message(bot_message)

                        # 发送回复
                        if response and response.text:
                            # 构建 @用户 前缀（群聊场景下需要在文本中包含 @用户名）
                            if response.at_user and incoming.sender_nick:
                                if response.markdown:
                                    self.reply_markdown(
                                        title="股票分析助手",
                                        text=f"@{incoming.sender_nick} " + response.text,
                                        incoming_message=incoming
                                    )
                                else:
                                    self.reply_text(response.text, incoming)

                    return AckMessage.STATUS_OK, 'OK'

                except Exception as e:
                    self.logger.error(f"[DingTalk Stream] 处理消息失败: {e}")
                    self.logger.exception(e)
                    return AckMessage.STATUS_SYSTEM_EXCEPTION, str(e)

        def create_handler(self) -> '_ChatbotHandler':
            """创建 SDK 需要的处理器实例"""
            return self._ChatbotHandler(self)

    def _parse_stream_message(self, incoming: Any, raw_data: dict) -> Optional[BotMessage]:
        """
        解析 Stream 消息为统一格式
        
        Args:
            incoming: ChatbotMessage 对象
            raw_data: 原始回调数据
        """
        try:
            raw_data = dict(raw_data or {})

            # 获取消息内容
            raw_content = incoming.text.content if incoming.text else ''

            # 提取命令（去除 @机器人）
            content = self._extract_command(raw_content)

            # 会话类型
            conversation_type = getattr(incoming, 'conversation_type', None)
            if conversation_type == '1':
                chat_type = ChatType.PRIVATE
            elif conversation_type == '2':
                chat_type = ChatType.GROUP
            else:
                chat_type = ChatType.UNKNOWN

            # 是否 @了机器人（Stream 模式下收到的消息一般都是 @机器人的）
            mentioned = True

            # 提取 sessionWebhook，便于异步推送
            session_webhook = (
                    getattr(incoming, 'session_webhook', None)
                    or raw_data.get('sessionWebhook')
                    or raw_data.get('session_webhook')
            )
            if session_webhook:
                raw_data['_session_webhook'] = session_webhook

            return BotMessage(
                platform='dingtalk',
                message_id=getattr(incoming, 'msg_id', '') or '',
                user_id=getattr(incoming, 'sender_id', '') or '',
                user_name=getattr(incoming, 'sender_nick', '') or '',
                chat_id=getattr(incoming, 'conversation_id', '') or '',
                chat_type=chat_type,
                content=content,
                raw_content=raw_content,
                mentioned=mentioned,
                mentions=[],
                timestamp=datetime.now(),
                raw_data=raw_data,
            )

        except Exception as e:
            logger.error(f"[DingTalk Stream] 解析消息失败: {e}")
            return None

    def _extract_command(self, text: str) -> str:
        """提取命令内容（去除 @机器人）"""
        import re
        text = re.sub(r'^@[\S]+\s*', '', text.strip())
        return text.strip()


class DingtalkStreamClient:
    """
    钉钉 Stream 模式客户端
    
    封装 dingtalk-stream SDK，提供简单的启动接口。
    
    使用方式：
        client = DingtalkStreamClient()
        client.start()  # 阻塞运行
        
        # 或者在后台运行
        client.start_background()
    """

    def __init__(
            self,
            client_id: Optional[str] = None,
            client_secret: Optional[str] = None
    ):
        """
        Args:
            client_id: 应用 AppKey（不传则从配置读取）
            client_secret: 应用 AppSecret（不传则从配置读取）
        """
        if not DINGTALK_STREAM_AVAILABLE:
            raise ImportError(
                "dingtalk-stream SDK 未安装。\n"
                "请运行: pip install dingtalk-stream"
            )

        from src.config import get_config
        config = get_config()

        self._client_id = client_id or getattr(config, 'dingtalk_app_key', None)
        self._client_secret = client_secret or getattr(config, 'dingtalk_app_secret', None)

        if not self._client_id or not self._client_secret:
            raise ValueError(
                "钉钉 Stream 模式需要配置 DINGTALK_APP_KEY 和 DINGTALK_APP_SECRET"
            )

        self._client: Optional[dingtalk_stream.DingTalkStreamClient] = None
        self._background_thread: Optional[threading.Thread] = None
        self._running = False

    def _create_message_handler(self) -> Callable[[BotMessage], BotResponse]:
        """创建消息处理函数"""

        def handle_message(message: BotMessage) -> BotResponse:
            from bot.dispatcher import get_dispatcher
            dispatcher = get_dispatcher()
            return dispatcher.dispatch(message)

        return handle_message

    def start(self) -> None:
        """
        启动 Stream 客户端（阻塞）
        
        此方法会阻塞当前线程，直到客户端停止。
        """
        logger.info("[DingTalk Stream] 正在启动...")

        # 创建凭证
        credential = dingtalk_stream.Credential(
            self._client_id,
            self._client_secret
        )

        # 创建客户端
        self._client = dingtalk_stream.DingTalkStreamClient(credential)

        # 注册消息处理器
        handler = DingtalkStreamHandler(self._create_message_handler())
        self._client.register_callback_handler(
            dingtalk_stream.chatbot.ChatbotMessage.TOPIC,
            handler.create_handler()
        )

        self._running = True
        logger.info("[DingTalk Stream] 客户端已启动，等待消息...")

        # 启动（阻塞）
        self._client.start_forever()

    def start_background(self) -> None:
        """
        在后台线程启动 Stream 客户端（非阻塞）
        
        适用于与其他服务（如 WebUI）同时运行的场景。
        """
        if self._background_thread and self._background_thread.is_alive():
            logger.warning("[DingTalk Stream] 客户端已在运行")
            return

        self._running = True
        self._background_thread = threading.Thread(
            target=self._run_in_background,
            daemon=True,
            name="DingtalkStreamClient"
        )
        self._background_thread.start()
        logger.info("[DingTalk Stream] 后台客户端已启动")

    def _run_in_background(self) -> None:
        """后台运行（处理异常和重连）"""
        while self._running:
            try:
                self.start()
            except Exception as e:
                logger.error(f"[DingTalk Stream] 运行异常: {e}")
                if self._running:
                    logger.info("[DingTalk Stream] 5 秒后重连...")
                    import time
                    time.sleep(5)

    def stop(self) -> None:
        """停止客户端"""
        self._running = False
        logger.info("[DingTalk Stream] 客户端已停止")

    @property
    def is_running(self) -> bool:
        """是否正在运行"""
        return self._running


# 全局客户端实例
_stream_client: Optional[DingtalkStreamClient] = None


def get_dingtalk_stream_client() -> Optional[DingtalkStreamClient]:
    """获取全局 Stream 客户端实例"""
    global _stream_client

    if _stream_client is None and DINGTALK_STREAM_AVAILABLE:
        try:
            _stream_client = DingtalkStreamClient()
        except (ImportError, ValueError) as e:
            logger.warning(f"[DingTalk Stream] 无法创建客户端: {e}")
            return None

    return _stream_client


def start_dingtalk_stream_background() -> bool:
    """
    在后台启动钉钉 Stream 客户端
    
    Returns:
        是否成功启动
    """
    client = get_dingtalk_stream_client()
    if client:
        client.start_background()
        return True
    return False
