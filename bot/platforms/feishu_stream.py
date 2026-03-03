# -*- coding: utf-8 -*-
"""
===================================
飞书 Stream 模式适配器
===================================

使用飞书官方 lark-oapi SDK 的 WebSocket 长连接模式接入机器人，
无需公网 IP 和 Webhook 配置。

优势：
- 不需要公网 IP 或域名
- 不需要配置 Webhook URL
- 通过 WebSocket 长连接接收消息
- 更简单的接入方式
- 内置自动重连和心跳保活

依赖：
pip install lark-oapi

飞书长连接文档：
https://open.feishu.cn/document/uAjLw4CM/ukTMukTMukTM/server-side-sdk/python--sdk/handle-events
"""

import json
import logging
import threading
from datetime import datetime
from typing import Optional, Callable

logger = logging.getLogger(__name__)

# 尝试导入飞书 SDK
try:
    import lark_oapi as lark
    from lark_oapi import ws
    from lark_oapi.api.im.v1 import (
        P2ImMessageReceiveV1,
        ReplyMessageRequest,
        ReplyMessageRequestBody,
        CreateMessageRequest,
        CreateMessageRequestBody,
    )

    FEISHU_SDK_AVAILABLE = True
except ImportError:
    FEISHU_SDK_AVAILABLE = False
    logger.warning("[Feishu Stream] lark-oapi SDK 未安装，Stream 模式不可用")
    logger.warning("[Feishu Stream] 请运行: pip install lark-oapi")

from bot.models import BotMessage, BotResponse, ChatType
from src.formatters import format_feishu_markdown, chunk_feishu_content
from src.config import get_config


class FeishuReplyClient:
    """
    飞书消息回复客户端
    
    使用飞书 API 发送回复消息。
    """

    def __init__(self, app_id: str, app_secret: str):
        """
        Args:
            app_id: 飞书应用 ID
            app_secret: 飞书应用密钥
        """
        if not FEISHU_SDK_AVAILABLE:
            raise ImportError("lark-oapi SDK 未安装")

        self._client = lark.Client.builder() \
            .app_id(app_id) \
            .app_secret(app_secret) \
            .log_level(lark.LogLevel.WARNING) \
            .build()

        # 获取配置的最大字节数
        config = get_config()
        self._max_bytes = getattr(config, 'feishu_max_bytes', 20000)

    def _send_interactive_card(self, content: str, message_id: Optional[str] = None,
                               chat_id: Optional[str] = None,
                               receive_id_type: str = "chat_id",
                               at_user: bool = False, user_id: Optional[str] = None) -> bool:
        """
        发送交互卡片消息（支持 Markdown 渲染）
        
        Args:
            content: Markdown 格式的内容
            message_id: 原消息 ID（回复时使用）
            chat_id: 会话 ID（主动发送时使用）
            receive_id_type: 接收者 ID 类型
            at_user: 是否 @用户
            user_id: 用户 open_id（at_user=True 时需要）
            
        Returns:
            是否发送成功
        """
        try:
            # 如果需要 @用户，在内容前添加 @ 标记
            final_content = content
            if at_user and user_id:
                final_content = f"<at user_id=\"{user_id}\"></at> {content}"
            
            # 构建交互卡片 payload
            card_data = {
                "config": {"wide_screen_mode": True},
                "elements": [
                    {
                        "tag": "div",
                        "text": {
                            "tag": "lark_md",
                            "content": final_content
                        }
                    }
                ]
            }

            content_json = json.dumps(card_data)

            if message_id:
                # 回复消息
                request = ReplyMessageRequest.builder() \
                    .message_id(message_id) \
                    .request_body(
                    ReplyMessageRequestBody.builder()
                    .content(content_json)
                    .msg_type("interactive")
                    .build()
                ) \
                    .build()
                response = self._client.im.v1.message.reply(request)
            else:
                # 主动发送消息
                request = CreateMessageRequest.builder() \
                    .receive_id_type(receive_id_type) \
                    .request_body(
                    CreateMessageRequestBody.builder()
                    .receive_id(chat_id)
                    .content(content_json)
                    .msg_type("interactive")
                    .build()
                ) \
                    .build()
                response = self._client.im.v1.message.create(request)

            if not response.success():
                logger.error(
                    f"[Feishu Stream] 发送交互卡片失败: code={response.code}, "
                    f"msg={response.msg}, log_id={response.get_log_id()}"
                )
                return False

            logger.debug(f"[Feishu Stream] 发送交互卡片成功")
            return True

        except Exception as e:
            logger.error(f"[Feishu Stream] 发送交互卡片异常: {e}")
            return False

    def reply_text(self, message_id: str, text: str, at_user: bool = False,
                   user_id: Optional[str] = None) -> bool:
        """
        回复文本消息（支持交互卡片和分段发送）
        
        Args:
            message_id: 原消息 ID
            text: 回复文本
            at_user: 是否 @用户
            user_id: 用户 open_id（at_user=True 时需要）
            
        Returns:
            是否发送成功
        """
        # 将文本转换为飞书 Markdown 格式
        formatted_text = format_feishu_markdown(text)

        # 检查是否需要分段发送
        content_bytes = len(formatted_text.encode('utf-8'))
        if content_bytes > self._max_bytes:
            logger.info(
                f"[Feishu Stream] 回复消息内容超长({content_bytes}字节)，将分批发送"
            )
            return chunk_feishu_content(
                formatted_text,
                self._max_bytes,
                lambda chunk: self._send_interactive_card(
                    chunk, message_id=message_id, at_user=at_user, user_id=user_id
                )
            )

        # 单条消息，使用交互卡片
        return self._send_interactive_card(
            formatted_text, message_id=message_id, at_user=at_user, user_id=user_id
        )

    def send_to_chat(self, chat_id: str, text: str,
                     receive_id_type: str = "chat_id") -> bool:
        """
        发送消息到指定会话（支持交互卡片和分段发送）
        
        Args:
            chat_id: 会话 ID
            text: 消息文本
            receive_id_type: 接收者 ID 类型，默认 chat_id
            
        Returns:
            是否发送成功
        """
        # 将文本转换为飞书 Markdown 格式
        formatted_text = format_feishu_markdown(text)

        # 检查是否需要分段发送
        content_bytes = len(formatted_text.encode('utf-8'))
        if content_bytes > self._max_bytes:
            logger.info(
                f"[Feishu Stream] 发送消息内容超长({content_bytes}字节)，将分批发送"
            )
            return chunk_feishu_content(
                formatted_text,
                self._max_bytes,
                lambda chunk: self._send_interactive_card(
                    chunk, chat_id=chat_id, receive_id_type=receive_id_type
                )
            )

        # 单条消息，使用交互卡片
        return self._send_interactive_card(
            formatted_text, chat_id=chat_id, receive_id_type=receive_id_type
        )


class FeishuStreamHandler:
    """
    飞书 Stream 模式消息处理器
    
    将 SDK 的事件转换为统一的 BotMessage 格式，
    并调用命令分发器处理。
    """

    def __init__(
            self,
            on_message: Callable[[BotMessage], BotResponse],
            reply_client: FeishuReplyClient
    ):
        """
        Args:
            on_message: 消息处理回调函数，接收 BotMessage 返回 BotResponse
            reply_client: 飞书回复客户端
        """
        self._on_message = on_message
        self._reply_client = reply_client
        self._logger = logger

    @staticmethod
    def _truncate_log_content(text: str, max_len: int = 200) -> str:
        """截断日志内容"""
        cleaned = text.replace("\n", " ").strip()
        if len(cleaned) > max_len:
            return f"{cleaned[:max_len]}..."
        return cleaned

    def _log_incoming_message(self, message: BotMessage) -> None:
        """记录收到的消息日志"""
        content = message.raw_content or message.content or ""
        summary = self._truncate_log_content(content)
        self._logger.info(
            "[Feishu Stream] Incoming message: msg_id=%s user_id=%s "
            "chat_id=%s chat_type=%s content=%s",
            message.message_id,
            message.user_id,
            message.chat_id,
            getattr(message.chat_type, "value", message.chat_type),
            summary,
        )

    def handle_message(self, event: 'P2ImMessageReceiveV1') -> None:
        """
        处理接收到的消息事件
        
        Args:
            event: 飞书消息接收事件
        """
        try:
            # 解析消息
            bot_message = self._parse_event_message(event)

            if bot_message is None:
                return

            self._log_incoming_message(bot_message)

            # 调用消息处理回调
            response = self._on_message(bot_message)

            # 发送回复
            if response and response.text:
                self._reply_client.reply_text(
                    message_id=bot_message.message_id,
                    text=response.text,
                    at_user=response.at_user,
                    user_id=bot_message.user_id if response.at_user else None
                )

        except Exception as e:
            self._logger.error(f"[Feishu Stream] 处理消息失败: {e}")
            self._logger.exception(e)

    def _parse_event_message(self, event: 'P2ImMessageReceiveV1') -> Optional[BotMessage]:
        """
        解析飞书事件消息为统一格式
        
        Args:
            event: P2ImMessageReceiveV1 事件对象
        """
        try:
            event_data = event.event
            if event_data is None:
                return None

            message_data = event_data.message
            sender_data = event_data.sender

            if message_data is None:
                return None

            # 只处理文本消息
            message_type = message_data.message_type or ""
            if message_type != "text":
                self._logger.debug(f"[Feishu Stream] 忽略非文本消息: {message_type}")
                return None

            # 解析消息内容
            content_str = message_data.content or "{}"
            try:
                content_json = json.loads(content_str)
                raw_content = content_json.get("text", "")
            except json.JSONDecodeError:
                raw_content = content_str

            # 提取命令（去除 @机器人）
            content = self._extract_command(raw_content, message_data.mentions)
            mentioned = "@" in raw_content or bool(message_data.mentions)

            # 获取发送者信息
            user_id = ""
            if sender_data and sender_data.sender_id:
                user_id = sender_data.sender_id.open_id or sender_data.sender_id.user_id or ""

            # 获取会话类型
            chat_type_str = message_data.chat_type or ""
            if chat_type_str == "group":
                chat_type = ChatType.GROUP
            elif chat_type_str == "p2p":
                chat_type = ChatType.PRIVATE
            else:
                chat_type = ChatType.UNKNOWN

            # 创建时间
            create_time = message_data.create_time
            try:
                if create_time:
                    timestamp = datetime.fromtimestamp(int(create_time) / 1000)
                else:
                    timestamp = datetime.now()
            except (ValueError, TypeError):
                timestamp = datetime.now()

            # 构建原始数据
            raw_data = {
                "header": {
                    "event_id": event.header.event_id if event.header else "",
                    "event_type": event.header.event_type if event.header else "",
                    "create_time": event.header.create_time if event.header else "",
                    "token": event.header.token if event.header else "",
                    "app_id": event.header.app_id if event.header else "",
                },
                "event": {
                    "message_id": message_data.message_id,
                    "chat_id": message_data.chat_id,
                    "chat_type": message_data.chat_type,
                    "content": message_data.content,
                }
            }

            return BotMessage(
                platform="feishu",
                message_id=message_data.message_id or "",
                user_id=user_id,
                user_name=user_id,  # 飞书不直接返回用户名
                chat_id=message_data.chat_id or "",
                chat_type=chat_type,
                content=content,
                raw_content=raw_content,
                mentioned=mentioned,
                mentions=[m.key or "" for m in (message_data.mentions or [])],
                timestamp=timestamp,
                raw_data=raw_data,
            )

        except Exception as e:
            self._logger.error(f"[Feishu Stream] 解析消息失败: {e}")
            return None

    def _extract_command(self, text: str, mentions: list) -> str:
        """
        提取命令内容（去除 @机器人）
        
        飞书的 @用户 格式是：@_user_1, @_user_2 等
        
        Args:
            text: 原始消息文本
            mentions: @提及列表
        """
        import re

        # 方式1: 通过 mentions 列表移除（精确匹配）
        for mention in (mentions or []):
            key = getattr(mention, 'key', '') or ''
            if key:
                text = text.replace(key, '')

        # 方式2: 正则兜底，移除飞书 @用户 格式（@_user_N）
        # 当 mentions 为空或未正确传递时生效
        text = re.sub(r'@_user_\d+\s*', '', text)

        # 清理多余空格
        return ' '.join(text.split())


class FeishuStreamClient:
    """
    飞书 Stream 模式客户端
    
    封装 lark-oapi SDK 的 WebSocket 客户端，提供简单的启动接口。
    
    使用方式：
        client = FeishuStreamClient()
        client.start()  # 阻塞运行
        
        # 或者在后台运行
        client.start_background()
    """

    def __init__(
            self,
            app_id: Optional[str] = None,
            app_secret: Optional[str] = None
    ):
        """
        Args:
            app_id: 应用 ID（不传则从配置读取）
            app_secret: 应用密钥（不传则从配置读取）
        """
        if not FEISHU_SDK_AVAILABLE:
            raise ImportError(
                "lark-oapi SDK 未安装。\n"
                "请运行: pip install lark-oapi"
            )

        from src.config import get_config
        config = get_config()

        self._app_id = app_id or getattr(config, 'feishu_app_id', None)
        self._app_secret = app_secret or getattr(config, 'feishu_app_secret', None)

        if not self._app_id or not self._app_secret:
            raise ValueError(
                "飞书 Stream 模式需要配置 FEISHU_APP_ID 和 FEISHU_APP_SECRET"
            )

        self._ws_client: Optional[ws.Client] = None
        self._reply_client: Optional[FeishuReplyClient] = None
        self._background_thread: Optional[threading.Thread] = None
        self._running = False

    def _create_message_handler(self) -> Callable[[BotMessage], BotResponse]:
        """创建消息处理函数"""

        def handle_message(message: BotMessage) -> BotResponse:
            from bot.dispatcher import get_dispatcher
            dispatcher = get_dispatcher()
            return dispatcher.dispatch(message)

        return handle_message

    def _create_event_handler(self) -> 'lark.EventDispatcherHandler':
        """创建事件分发处理器"""
        # 创建回复客户端
        self._reply_client = FeishuReplyClient(self._app_id, self._app_secret)

        # 创建消息处理器
        handler = FeishuStreamHandler(
            self._create_message_handler(),
            self._reply_client
        )

        # 创建并注册事件处理器
        # 注意：encrypt_key 和 verification_token 在长连接模式下不是必需的
        # 但 SDK 要求传入（可以为空字符串）
        from src.config import get_config
        config = get_config()

        encrypt_key = getattr(config, 'feishu_encrypt_key', '') or ''
        verification_token = getattr(config, 'feishu_verification_token', '') or ''

        event_handler = lark.EventDispatcherHandler.builder(
            encrypt_key=encrypt_key,
            verification_token=verification_token,
            level=lark.LogLevel.WARNING
        ).register_p2_im_message_receive_v1(
            handler.handle_message
        ).build()

        return event_handler

    def start(self) -> None:
        """
        启动 Stream 客户端（阻塞）
        
        此方法会阻塞当前线程，直到客户端停止。
        """
        logger.info("[Feishu Stream] 正在启动...")

        # 创建事件处理器
        event_handler = self._create_event_handler()

        # 创建 WebSocket 客户端
        self._ws_client = ws.Client(
            app_id=self._app_id,
            app_secret=self._app_secret,
            event_handler=event_handler,
            log_level=lark.LogLevel.WARNING,
            auto_reconnect=True
        )

        self._running = True
        logger.info("[Feishu Stream] 客户端已启动，等待消息...")

        # 启动（阻塞）
        self._ws_client.start()

    def start_background(self) -> None:
        """
        在后台线程启动 Stream 客户端（非阻塞）
        
        适用于与其他服务（如 WebUI）同时运行的场景。
        """
        if self._background_thread and self._background_thread.is_alive():
            logger.warning("[Feishu Stream] 客户端已在运行")
            return

        self._running = True
        self._background_thread = threading.Thread(
            target=self._run_in_background,
            daemon=True,
            name="FeishuStreamClient"
        )
        self._background_thread.start()
        logger.info("[Feishu Stream] 后台客户端已启动")

    def _run_in_background(self) -> None:
        """后台运行（处理异常和重连）"""
        import time

        while self._running:
            try:
                self.start()
            except Exception as e:
                logger.error(f"[Feishu Stream] 运行异常: {e}")
                if self._running:
                    logger.info("[Feishu Stream] 5 秒后重连...")
                    time.sleep(5)

    def stop(self) -> None:
        """停止客户端"""
        self._running = False
        logger.info("[Feishu Stream] 客户端已停止")

    @property
    def is_running(self) -> bool:
        """是否正在运行"""
        return self._running


# 全局客户端实例
_stream_client: Optional[FeishuStreamClient] = None


def get_feishu_stream_client() -> Optional[FeishuStreamClient]:
    """获取全局 Stream 客户端实例"""
    global _stream_client

    if _stream_client is None and FEISHU_SDK_AVAILABLE:
        try:
            _stream_client = FeishuStreamClient()
        except (ImportError, ValueError) as e:
            logger.warning(f"[Feishu Stream] 无法创建客户端: {e}")
            return None

    return _stream_client


def start_feishu_stream_background() -> bool:
    """
    在后台启动飞书 Stream 客户端
    
    Returns:
        是否成功启动
    """
    client = get_feishu_stream_client()
    if client:
        client.start_background()
        return True
    return False
