# -*- coding: utf-8 -*-
"""
===================================
企业微信智能机器人（AI Bot）推送渠道
===================================

通过官方长连接 ``aibot_send_msg`` 帧向已存在的会话主动推送通知，
作为 notification_sender 渠道族的新成员（与 wechat_sender webhook 等
渠道同接口接入，见 ``src/notification.py`` 的渠道分发）。

协议约束（官方文档 developer.work.weixin.qq.com/document/path/101463）：
- **前置条件**：``aibot_send_msg`` 只能推送到已存在的会话——目标用户须先
  给机器人发过消息（单聊 chatid=用户 userid，群聊 chatid=群 ID）。无
  webhook 式单向推送 REST API，本渠道不能替代群机器人 webhook。
- **限流**：会话级 30 条/分钟、1000 条/小时、同用户并发 3 条。本渠道用
  独立的 :class:`AibotPushRateLimiter` 在推送侧对齐（Phase 1 的
  ``WecomAibotHandler`` 会话回复限流是另一份预算，互不影响）。
- **默认关**：需同时配置 ``WECOM_AIBOT_NOTIFY_ENABLED=true`` 与
  ``WECOM_AIBOT_NOTIFY_CHATID``（逗号分隔多会话）才会被视为已配置渠道。
- 连接复用：经 ``bot.platforms.wecom_aibot.get_wecom_aibot_client()` 取
  全局长连接客户端；客户端未运行（未启用/断线/认证放弃）时推送失败降级
  返回 False，不影响其它渠道。

旧企微 webhook 渠道（wechat_sender.py）保持零改动（验收第 5 条：新旧
渠道并存）。
"""

import logging
import threading
import time
from collections import defaultdict, deque
from typing import Any, Dict, List, Optional

from src.config import Config
from src.formatters import strip_hidden_markdown_metadata

logger = logging.getLogger(__name__)


class AibotPushRateLimiter:
    """
    aibot 推送渠道独立限流器

    官方会话级上限口径：
    - 30 条 / 分钟（滑动窗口）
    - 1000 条 / 小时（滑动窗口）
    - 同会话并发 3 条（推送在途未回执计数，回执后释放）

    分钟/小时预算在 :meth:`acquire` 时消耗（无论后续是否 release），
    并发槽由返回的 slot 句柄持有、``release()`` 释放。线程安全。
    """

    _WINDOW_SECONDS_MINUTE = 60.0
    _WINDOW_SECONDS_HOUR = 3600.0

    def __init__(
        self,
        max_per_minute: int = 30,
        max_per_hour: int = 1000,
        max_concurrent_per_chat: int = 3,
    ):
        self.max_per_minute = max_per_minute
        self.max_per_hour = max_per_hour
        self.max_concurrent_per_chat = max_concurrent_per_chat
        self._minute_events: Dict[str, deque] = defaultdict(deque)
        self._hour_events: Dict[str, deque] = defaultdict(deque)
        self._in_flight: Dict[str, int] = defaultdict(int)
        self._lock = threading.Lock()

    def _evict(self, chat_id: str, now: float) -> None:
        minute_window_start = now - self._WINDOW_SECONDS_MINUTE
        hour_window_start = now - self._WINDOW_SECONDS_HOUR
        minute_events = self._minute_events[chat_id]
        while minute_events and minute_events[0] <= minute_window_start:
            minute_events.popleft()
        hour_events = self._hour_events[chat_id]
        while hour_events and hour_events[0] <= hour_window_start:
            hour_events.popleft()

    def acquire(self, chat_id: str) -> Optional["_PushSlot"]:
        """获取一个推送名额；限流/并发超限时返回 None（不占用任何预算）。"""
        with self._lock:
            now = time.time()
            self._evict(chat_id, now)

            if len(self._minute_events[chat_id]) >= self.max_per_minute:
                return None
            if len(self._hour_events[chat_id]) >= self.max_per_hour:
                return None
            if self._in_flight[chat_id] >= self.max_concurrent_per_chat:
                return None

            self._minute_events[chat_id].append(now)
            self._hour_events[chat_id].append(now)
            self._in_flight[chat_id] += 1
            return _PushSlot(self, chat_id)

    def _release_slot(self, chat_id: str) -> None:
        with self._lock:
            count = self._in_flight.get(chat_id, 0)
            if count <= 1:
                self._in_flight.pop(chat_id, None)
            else:
                self._in_flight[chat_id] = count - 1


class _PushSlot:
    """一次推送占用的并发槽句柄；release 幂等。"""

    def __init__(self, limiter: AibotPushRateLimiter, chat_id: str):
        self._limiter = limiter
        self._chat_id = chat_id
        self._released = False

    def release(self) -> None:
        if self._released:
            return
        self._released = True
        self._limiter._release_slot(self._chat_id)


class WecomAibotSender:
    """
    企业微信智能机器人推送渠道（aibot_send_msg）

    与其它渠道同接口：``send_to_wecom_aibot(content, *, timeout_seconds=None)``
    返回 bool。失败（未启用/未配置/未连接/限流/回执错误/异常）一律记录日志
    并返回 False，不抛异常、不阻断其它渠道。
    """

    _PUSH_TIMEOUT_SECONDS = 10.0

    def __init__(
        self,
        config: Config,
        rate_limiter: Optional[AibotPushRateLimiter] = None,
    ):
        """
        Args:
            config: 全局配置对象
            rate_limiter: 可注入限流器（测试用）；默认每实例独立一份
        """
        self._notify_enabled = bool(
            getattr(config, "wecom_aibot_notify_enabled", False)
        )
        self._notify_chatids = self._parse_chatids(
            getattr(config, "wecom_aibot_notify_chatid", None)
        )
        self._push_limiter = rate_limiter or AibotPushRateLimiter()

    @staticmethod
    def _parse_chatids(raw_value: Any) -> List[str]:
        """WECOM_AIBOT_NOTIFY_CHATID 逗号/空白分隔的多会话列表。"""
        if not raw_value:
            return []
        if isinstance(raw_value, (list, tuple, set)):
            items = list(raw_value)
        else:
            items = str(raw_value).replace(";", ",").replace("，", ",").split(",")
        chatids = []
        for item in items:
            chat_id = str(item).strip()
            if chat_id and chat_id not in chatids:
                chatids.append(chat_id)
        return chatids

    @property
    def is_configured(self) -> bool:
        """渠道是否被显式配置启用（enabled + 至少一个目标会话）。"""
        return self._notify_enabled and bool(self._notify_chatids)

    def send_to_wecom_aibot(
        self, content: str, *, timeout_seconds: Optional[float] = None
    ) -> bool:
        """
        推送消息到配置的目标会话（aibot_send_msg 帧）

        Args:
            content: Markdown 格式消息内容
            timeout_seconds: 单会话推送回执等待秒数（默认 10s）

        Returns:
            全部目标会话推送成功返回 True；任一失败/被限流返回 False
        """
        if not self._notify_enabled:
            logger.debug("[WeCom AI Bot] WECOM_AIBOT_NOTIFY_ENABLED 未开启，跳过推送")
            return False

        if not self._notify_chatids:
            logger.warning(
                "[WeCom AI Bot] WECOM_AIBOT_NOTIFY_CHATID 未配置，跳过推送"
            )
            return False

        sanitized_content = strip_hidden_markdown_metadata(content).strip()
        if not sanitized_content:
            logger.warning("[WeCom AI Bot] 推送内容为空，跳过")
            return False

        # 惰性导入：SDK 缺失时 get_wecom_aibot_client 返回 None（含安装提示日志），
        # 由下方 client 为空的降级分支统一处理
        from bot.platforms.wecom_aibot import get_wecom_aibot_client

        client = get_wecom_aibot_client()
        if client is None or not client.is_running:
            logger.warning(
                "[WeCom AI Bot] 长连接客户端未运行，推送失败降级。"
                "前置条件：WECOM_AIBOT_ENABLED=true 且客户端在线，"
                "且目标用户须先与机器人建过会话（aibot_send_msg 只能推送到"
                "已存在的会话）"
            )
            return False

        body = {"msgtype": "markdown", "markdown": {"content": sanitized_content}}
        timeout = timeout_seconds if timeout_seconds is not None else self._PUSH_TIMEOUT_SECONDS

        all_ok = True
        for chat_id in self._notify_chatids:
            slot = self._push_limiter.acquire(chat_id)
            if slot is None:
                logger.warning(
                    "[WeCom AI Bot] 推送触发限流（30条/分、1000条/时、同会话"
                    "并发3条），本条丢弃: chat=%s",
                    chat_id,
                )
                all_ok = False
                continue

            try:
                ack_frame = client.push_message(chat_id, body, timeout)
            except Exception as exc:  # 防御分支：push_message 内部已捕获
                logger.error("[WeCom AI Bot] 推送异常 (chat=%s): %s", chat_id, exc)
                ack_frame = None
            finally:
                slot.release()

            if ack_frame is None:
                all_ok = False
            else:
                logger.info("[WeCom AI Bot] 推送成功: chat=%s", chat_id)

        return all_ok
