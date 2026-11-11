# -*- coding: utf-8 -*-
"""
===================================
企业微信智能机器人（AI Bot）长连接适配器
===================================

使用官方 ``wecom-aibot-python-sdk`` 通过 WebSocket 长连接接入企业微信智能机器人，
无需公网 IP 和回调 URL 配置（回调 URL 模式需要公网 HTTPS，自部署场景不可行，
本仓库明确不做）。

协议要点（官方文档 developer.work.weixin.qq.com/document/path/101463 / 101138）：
- 连接地址 ``wss://openws.work.weixin.qq.com``，认证走 ``aibot_subscribe`` 帧
  （bot_id + secret，secret 是长连接专用凭据，与 Webhook 模式的
  Token/EncodingAESKey 不同）。
- 心跳：每 30 秒发送 ``ping`` 帧，服务端停止收到心跳即断开；SDK 内置心跳与
  指数退避重连（1s → 2s → 4s … 上限 30s）。
- 单机器人仅一条有效连接：新连接订阅成功会踢掉旧连接。本适配器以
  「单后台线程 + 单 SDK 客户端实例 + start_background 互斥」防护重连风暴。
- 认证失败（subscribe errcode != 0）时 SDK 只上报 error 不重试，本适配器
  在适配器层做指数退避重试，超过上限放弃并告警。
- 收消息走 ``aibot_msg_callback`` 帧（body.msgid 用于排重）；回复走
  ``aibot_respond_msg`` 帧并透传回调帧 headers.req_id；reply_stream
  （body.msgtype=stream，10 分钟内须 finish）默认关闭，可用
  WECOM_AIBOT_REPLY_STREAM 开启。
- 会话级限流：单会话回复上限 30 条/分钟（另 1000 条/小时），本适配器复用
  bot.dispatcher.RateLimiter 在入口对齐 30 条/分钟；超限消息丢弃并告警
  （回执也占额度，不回执以免加剧超限）。

已知限制（Phase 1 标注，不阻塞）：
- 非超管创建的机器人，回调 ``from.userid`` 为密文（官方要求通过自建应用/
  机器人的 userid 转换接口换取明文）。官方 SDK v1.0.2 未内置该转换
  （源码核查：仅含文件解密 crypto_utils 与文件下载 api，无 userid 转换）。
  本适配器原样透传 userid；涉及按用户区分的逻辑（如 dispatcher 管理员名单）
  在密文场景下语义不变（同一密文稳定指向同一用户）。

依赖：
pip install wecom-aibot-python-sdk

官方 SDK：https://github.com/WecomTeam/wecom-aibot-python-sdk
"""

import asyncio
import logging
import threading
import time
import uuid
from collections import defaultdict, deque
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# 官方长连接协议命令常量（developer.work.weixin.qq.com/document/path/101463）
AIBOT_SUBSCRIBE_CMD = "aibot_subscribe"
AIBOT_RESPOND_CMD = "aibot_respond_msg"
AIBOT_CALLBACK_CMD = "aibot_msg_callback"
WECOM_AIBOT_WS_URL = "wss://openws.work.weixin.qq.com"

# 尝试导入官方 SDK（可选依赖，缺失时模块仍可导入、功能关闭）
try:
    from aibot import WSClient, WSClientOptions

    WECOM_AIBOT_SDK_AVAILABLE = True
except ImportError:
    WECOM_AIBOT_SDK_AVAILABLE = False
    WSClient = None
    WSClientOptions = None
    logger.warning("[WeCom AI Bot] wecom-aibot-python-sdk SDK 未安装，长连接模式不可用")
    logger.warning("[WeCom AI Bot] 请运行: pip install wecom-aibot-python-sdk")

from bot.dispatcher import RateLimiter
from bot.models import BotMessage, ChatType
from src.config import get_config


def _extract_command(text: str) -> str:
    """提取命令内容（去除群聊中 @机器人 前缀）"""
    import re

    text = re.sub(r"^@\S+\s*", "", text.strip())
    return text.strip()


class _OutboundGateSlot:
    """共享出站闸的槽位句柄；release 幂等。"""

    __slots__ = ("_gate", "_chat_id", "_released")

    def __init__(self, gate: "WecomAibotOutboundGate", chat_id: str):
        self._gate = gate
        self._chat_id = chat_id
        self._released = False

    def release(self) -> None:
        if self._released:
            return
        self._released = True
        self._gate._release(self._chat_id)


class WecomAibotOutboundGate:
    """共享会话级出站并发闸（官方单会话并发 ≤3 条在途）

    传输层权威闸（r4 修复 OR-COR-f5a96c8b）：被动回复（aibot_respond_msg）、
    来源会话回推与静态推送（aibot_send_msg，send_to_chat）三条出站路径统一
    经同一实例计数——回复、回推与静态推送叠加也不会超过同会话并发上限
    （此前并发上限只在静态 sender 局部限流器内，回复/回推路径绕过）。

    拒绝语义与双窗口配额拒绝同型：try_acquire 返回 None → 调用方拒发并
    打告警日志、双窗口零记账（不消耗额度）；槽位在发送完成（回执到达，
    无论成败）后释放，release 幂等。
    """

    def __init__(self, max_concurrent_per_chat: int = 3):
        self._max_concurrent_per_chat = max_concurrent_per_chat
        self._in_flight: Dict[str, int] = defaultdict(int)
        self._lock = threading.Lock()

    def try_acquire(self, chat_id: Optional[str]) -> Optional[_OutboundGateSlot]:
        key = chat_id or "unknown"
        with self._lock:
            if self._in_flight[key] >= self._max_concurrent_per_chat:
                return None
            self._in_flight[key] += 1
            return _OutboundGateSlot(self, key)

    def _release(self, chat_id: str) -> None:
        with self._lock:
            count = self._in_flight.get(chat_id, 0)
            if count <= 1:
                self._in_flight.pop(chat_id, None)
            else:
                self._in_flight[chat_id] = count - 1

    def in_flight(self, chat_id: Optional[str]) -> int:
        """诊断/测试用：某会话当前在途消息数。"""
        with self._lock:
            return self._in_flight.get(chat_id or "unknown", 0)


# 传输层共享闸（模块级单例——三条出站路径必须共用同一实例才能合计计数）
_WECOM_AIBOT_OUTBOUND_GATE = WecomAibotOutboundGate(max_concurrent_per_chat=3)


def _reset_outbound_gate() -> None:
    """重置共享出站闸（仅测试用）。

    原地清空在途计数而非重绑实例——模块级单例的身份必须全程稳定，
    否则 import 期绑定的引用与传输层读取的全局会分叉。
    """
    with _WECOM_AIBOT_OUTBOUND_GATE._lock:
        _WECOM_AIBOT_OUTBOUND_GATE._in_flight.clear()


# ------------------------------------------------------------------ #
#  长文本分片（r5 OR-COR-7ab3e812：4000B 上限此前从未被发送路径消费）   #
# ------------------------------------------------------------------ #

_WECOM_AIBOT_MAX_TEXT_BYTES_DEFAULT = 4000


def _wecom_aibot_max_text_bytes() -> int:
    """渠道 markdown 字节上限——消费 notification_capabilities 的声明
    （wecom_aibot.max_text_bytes=4000），单一事实源；异常时回退默认值。"""
    try:
        from src.notification_capabilities import get_channel_profile

        limit = get_channel_profile("wecom_aibot").max_text_bytes
        return int(limit) if limit else _WECOM_AIBOT_MAX_TEXT_BYTES_DEFAULT
    except Exception:  # pragma: no cover - 防御分支（声明缺失时退回默认）
        return _WECOM_AIBOT_MAX_TEXT_BYTES_DEFAULT


def _utf8_safe_cut_offset(encoded: bytes, limit: int) -> int:
    """返回 encoded 上 ≤limit 的最大绝对切点，且不落在 UTF-8 连续字节上。

    连续字节（continuation byte）形如 0b10xxxxxx；切点落在其上意味着把
    一个多字节字符切成两半——回退到合法字符边界。limit ≥ 总长时返回
    总长（无需切分）。
    """
    if limit >= len(encoded):
        return len(encoded)
    cut = limit
    while cut > 0 and (encoded[cut] & 0xC0) == 0x80:
        cut -= 1
    return cut


def _split_oversized_line_bytes(line: str, max_bytes: int) -> list:
    """把超出上限的单行按 UTF-8 安全边界切成 ≤max_bytes 的多段。"""
    encoded = line.encode("utf-8")
    pieces = []
    start = 0
    total = len(encoded)
    while start < total:
        cut = _utf8_safe_cut_offset(encoded, min(start + max_bytes, total))
        if cut <= start:  # 理论不可达（单字符 ≤4B << max_bytes），兜底防死循环
            cut = min(start + max_bytes, total)
        pieces.append(encoded[start:cut].decode("utf-8"))
        start = cut
    return pieces


def _split_wecom_aibot_text_chunks(
    text: str, max_bytes: Optional[int] = None
) -> list:
    """把文本切成每片 ≤max_bytes 字节（UTF-8）的列表。

    切分优先级：整段 ≤ 上限 → 原样单条；否则按行贪心累积（段落边界由
    空行自然承载，不被切开）；单行自身超限 → 字节安全兜底切分（绝不切开
    多字节字符）。分片拼接可还原原文（无损）。

    供 ``WecomAibotClient.send_to_chat``（静态推送与来源会话回推的共享
    咽喉点）消费 notification_capabilities 声明的 max_text_bytes。
    """
    if not text:
        return []
    limit = max_bytes or _wecom_aibot_max_text_bytes()
    if len(text.encode("utf-8")) <= limit:
        return [text]

    chunks: list = []
    current_lines: list = []
    current_bytes = 0
    for line in text.split("\n"):
        joiner = 1 if current_lines else 0  # 行间 "\n" 的 1 字节
        line_cost = len(line.encode("utf-8")) + joiner
        if current_bytes + line_cost <= limit:
            current_lines.append(line)
            current_bytes += line_cost
            continue
        if current_lines:
            chunks.append("\n".join(current_lines))
            current_lines = []
            current_bytes = 0
        if len(line.encode("utf-8")) + 0 <= limit:
            current_lines.append(line)
            current_bytes = len(line.encode("utf-8"))
            continue
        # 单行自身超限：字节安全兜底切分
        for piece in _split_oversized_line_bytes(line, limit):
            chunks.append(piece)
        # 兜底片段已自封行，后续行从新片开始
        current_lines = []
        current_bytes = 0
    if current_lines:
        chunks.append("\n".join(current_lines))
    return chunks


class WecomAibotHandler:
    """
    企微智能机器人消息处理器

    将 ``aibot_msg_callback`` 帧转换为统一 BotMessage，做 msgid 排重与会话级
    限流（30 条/分钟），在独立线程池中调用命令分发器（避免阻塞 SDK 事件循环
    上的 30s 心跳），再经 ``aibot_respond_msg`` 帧回复。
    """

    _MSGID_CACHE_SIZE = 512

    def __init__(
        self,
        sdk_client: Optional[Any] = None,
        reply_stream_enabled: bool = False,
    ):
        """
        Args:
            sdk_client: 官方 SDK WSClient 实例（用于 aibot_respond_msg 回复）
            reply_stream_enabled: 是否用 stream 流式回复（默认 False，一次性
                markdown 回复；True 时单帧 finish=True 的 stream 回复）
        """
        self.sdk_client = sdk_client
        self._reply_stream_enabled = reply_stream_enabled
        self._loop: Optional[asyncio.AbstractEventLoop] = None

        # msgid 排重（协议要求：msgid 是回调唯一性标志）
        self._seen_msgids: set = set()
        self._msgid_order: deque = deque()
        self._dedup_lock = threading.Lock()

        # 会话级限流：复用 dispatcher 的 RateLimiter，对齐官方 30 条/分钟
        self._rate_limiter = RateLimiter(max_requests=30, window_seconds=60)

        # 回复（出站）双窗口配额：官方单会话发送上限 30 条/分钟且 1000 条/小时
        # （aibot_respond_msg 被动回复与 aibot_send_msg 主动推送共用该额度）。
        # 与入站限流（_rate_limiter）分离计数，避免入站消费挤占出站配额。
        self._reply_ack_timeout_seconds = 15.0  # 每帧回执等待上限（r7 串行分片）
        self._outbound_minute_limiter = RateLimiter(max_requests=30, window_seconds=60)
        self._outbound_hour_limiter = RateLimiter(max_requests=1000, window_seconds=3600)
        # 配额决策临界区锁：两窗口的检查与扣量必须不可分割（OR-COM-62e2b418）
        self._outbound_quota_lock = threading.Lock()

        # 不同会话可并行，单会话保持 FIFO（飞书 Stream 处理器同款模式）
        self._executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="wecom-msg")
        self._pending_messages: dict = {}
        self._active_conversations: set = set()
        self._queue_lock = threading.Lock()
        self._shutdown = False

    # ------------------------------------------------------------------ #
    #  SDK 事件入口                                                       #
    # ------------------------------------------------------------------ #

    def handle_frame(self, frame: dict) -> None:
        """处理一条 aibot_msg_callback 帧（SDK 事件循环线程上同步调用）"""
        try:
            bot_message = self._parse_frame(frame)
            if bot_message is None:
                return

            if self._is_duplicate_msgid(bot_message.message_id):
                logger.warning(
                    "[WeCom AI Bot] 重复消息已丢弃: msgid=%s",
                    bot_message.message_id,
                )
                return

            conversation_key = self._conversation_key(bot_message)
            if not self._allow_conversation(conversation_key):
                logger.warning(
                    "[WeCom AI Bot] 会话频率限制（30条/分钟），消息已丢弃: key=%s",
                    conversation_key,
                )
                return

            self._log_incoming_message(bot_message)
            self._enqueue_message(bot_message)
        except Exception as exc:
            logger.error("[WeCom AI Bot] 处理消息失败: %s", exc)
            logger.exception(exc)

    # ------------------------------------------------------------------ #
    #  解析与防护                                                         #
    # ------------------------------------------------------------------ #

    def _parse_frame(self, frame: dict) -> Optional[BotMessage]:
        """解析 aibot_msg_callback 帧为统一消息（Phase 1 仅处理文本消息）"""
        try:
            body = (frame or {}).get("body") or {}
            if body.get("msgtype") != "text":
                logger.debug(
                    "[WeCom AI Bot] 忽略非文本消息: msgtype=%s", body.get("msgtype")
                )
                return None

            raw_content = (body.get("text") or {}).get("content", "") or ""
            content = _extract_command(raw_content)

            from_info = body.get("from") or {}
            # 已知限制：非超管创建的机器人 from.userid 为密文，原样透传
            # （官方 SDK v1.0.2 不含 userid 转换；转换接口属 Phase 2 评估项）。
            user_id = from_info.get("userid", "") or ""

            chattype = body.get("chattype")
            if chattype == "single":
                chat_type = ChatType.PRIVATE
            elif chattype == "group":
                chat_type = ChatType.GROUP
            else:
                chat_type = ChatType.UNKNOWN

            # chatid 仅群聊返回；单聊用 userid 充当会话标识
            chat_id = body.get("chatid") or user_id

            req_id = ((frame or {}).get("headers") or {}).get("req_id", "")

            return BotMessage(
                platform="wecom",
                message_id=body.get("msgid", "") or "",
                user_id=user_id,
                user_name=user_id,
                chat_id=chat_id,
                chat_type=chat_type,
                content=content,
                raw_content=raw_content,
                mentioned=True,
                mentions=[],
                timestamp=datetime.now(),
                raw_data={
                    "_wecom_req_id": req_id,
                    "_wecom_frame": frame or {},
                },
            )
        except Exception as exc:
            logger.error("[WeCom AI Bot] 解析消息失败: %s", exc)
            return None

    def _is_duplicate_msgid(self, msgid: str) -> bool:
        """msgid 排重；缓存有界，最旧条目淘汰后可再次处理"""
        if not msgid:
            return False

        with self._dedup_lock:
            if msgid in self._seen_msgids:
                return True
            self._seen_msgids.add(msgid)
            self._msgid_order.append(msgid)
            while len(self._msgid_order) > self._MSGID_CACHE_SIZE:
                oldest = self._msgid_order.popleft()
                self._seen_msgids.discard(oldest)
            return False

    def _conversation_key(self, bot_message: BotMessage) -> str:
        """会话级限流的键：单聊按 userid，群聊按 chatid"""
        return bot_message.chat_id or bot_message.user_id or "unknown"

    def _allow_conversation(self, conversation_key: str) -> bool:
        """入站 flood 防护（30 条/分钟）；回复配额另见 _allow_outbound_reply"""
        return self._rate_limiter.is_allowed(conversation_key)

    def _allow_outbound_reply(self, conversation_key: str) -> bool:
        """出站回复双窗口配额（官方单会话发送上限：30 条/分钟且 1000 条/小时）

        原子决策（OR-COM-62e2b418）：单一临界区内先只读检查两窗口
        （RateLimiter.would_allow，不记账），均允许才统一扣量
        （RateLimiter.record）；并发线程（命令回执线程 × 分析完成通知线程）
        经进程内锁串行化，检查与扣量不可分割——不会双双过检导致超额，
        分钟窗口拒绝也不消耗小时额度。任一窗口拒绝即返回 False（调用方
        丢弃回复并记日志，不回执以免加剧配额压力、不排队积压）。
        """
        with self._outbound_quota_lock:
            if not self._outbound_minute_limiter.would_allow(conversation_key):
                return False
            if not self._outbound_hour_limiter.would_allow(conversation_key):
                return False
            self._outbound_minute_limiter.record(conversation_key)
            self._outbound_hour_limiter.record(conversation_key)
            return True

    def _acquire_outbound_slot(self, conversation_key: str) -> Optional[str]:
        """可用性前置的配额获取（r4：记账不得先于发送确认）

        与 :meth:`_allow_outbound_reply` 同一临界区原子语义，另在扣量前
        检查 SDK 事件循环可用性：循环不可用（如重连周期间隙）直接拒绝且
        **零记账**——不会出现"记账了但发不出去"，恢复后额度完整可用。

        Returns:
            本次发送的唯一 token（uuid4）；双窗口记录携带该 token，失败
            退款时按 token 精确移除本次记录（r5）。被拒绝时返回 None。
        """
        with self._outbound_quota_lock:
            # 认证闸（r8 OR-COR-36f9842a）：事件由所属 client 接线；未接线
            # （独立 handler/测试 harness）时不做认证闸，保持既有行为。
            auth_event = getattr(self, "_authenticated_event", None)
            if auth_event is not None and not auth_event.is_set():
                logger.warning(
                    "[WeCom AI Bot] 长连接未完成认证（连接中/重连中），"
                    "回复已丢弃（零记账）: key=%s",
                    conversation_key,
                )
                return None
            if not self._outbound_minute_limiter.would_allow(conversation_key):
                logger.warning(
                    "[WeCom AI Bot] 会话回复超限（分钟30条或小时1000条配额），"
                    "回复已丢弃: key=%s",
                    conversation_key,
                )
                return None
            if not self._outbound_hour_limiter.would_allow(conversation_key):
                logger.warning(
                    "[WeCom AI Bot] 会话回复超限（分钟30条或小时1000条配额），"
                    "回复已丢弃: key=%s",
                    conversation_key,
                )
                return None
            loop = self._loop
            if loop is None or loop.is_closed():
                logger.error("[WeCom AI Bot] 无法回复：SDK 事件循环不可用")
                return None
            token = uuid.uuid4().hex
            self._outbound_minute_limiter.record(conversation_key, token=token)
            self._outbound_hour_limiter.record(conversation_key, token=token)
            return token

    def _refund_outbound_send(self, conversation_key: str, token: str) -> None:
        """发送失败回滚：在配额临界区内按发送标识精确退还双窗口本次扣量
        （r4/r5）——同会话发送交错完成时不会退错记录。"""
        with self._outbound_quota_lock:
            self._outbound_minute_limiter.refund(conversation_key, token=token)
            self._outbound_hour_limiter.refund(conversation_key, token=token)

    @staticmethod
    def _outbound_key_from_frame(frame: dict) -> str:
        """从回调帧提取回复配额的会话键（群聊 chatid / 单聊 from.userid）"""
        body = (frame or {}).get("body") or {}
        return (
            body.get("chatid")
            or (body.get("from") or {}).get("userid")
            or "unknown"
        )

    @staticmethod
    def _truncate_log_content(text: str, max_len: int = 200) -> str:
        cleaned = text.replace("\n", " ").strip()
        if len(cleaned) > max_len:
            return f"{cleaned[:max_len]}..."
        return cleaned

    def _log_incoming_message(self, message: BotMessage) -> None:
        content = message.raw_content or message.content or ""
        summary = self._truncate_log_content(content)
        logger.info(
            "[WeCom AI Bot] Incoming message: msg_id=%s user_id=%s chat_id=%s "
            "chat_type=%s content=%s",
            message.message_id,
            message.user_id,
            message.chat_id,
            getattr(message.chat_type, "value", message.chat_type),
            summary,
        )

    # ------------------------------------------------------------------ #
    #  单会话 FIFO 线程池（避免阻塞 SDK 事件循环上的心跳）                  #
    # ------------------------------------------------------------------ #

    def _enqueue_message(self, bot_message: BotMessage) -> None:
        if self._shutdown:
            logger.debug("[WeCom AI Bot] 处理器已停止，丢弃消息")
            return

        conversation_key = self._conversation_key(bot_message)
        should_start_worker = False

        with self._queue_lock:
            self._pending_messages.setdefault(conversation_key, deque()).append(bot_message)
            if conversation_key not in self._active_conversations:
                self._active_conversations.add(conversation_key)
                should_start_worker = True

        if should_start_worker:
            try:
                self._executor.submit(self._drain_conversation, conversation_key)
            except RuntimeError as exc:
                with self._queue_lock:
                    self._active_conversations.discard(conversation_key)
                    self._pending_messages.pop(conversation_key, None)
                logger.error("[WeCom AI Bot] 无法启动消息处理线程: %s", exc)

    def _drain_conversation(self, conversation_key: str) -> None:
        while True:
            with self._queue_lock:
                queue = self._pending_messages.get(conversation_key)
                if not queue:
                    self._pending_messages.pop(conversation_key, None)
                    self._active_conversations.discard(conversation_key)
                    return
                bot_message = queue.popleft()

            self._process_message(bot_message)

    def _process_message(self, bot_message: BotMessage) -> None:
        """分发到命令分发器并回复（工作线程上下文，无事件循环竞争）"""
        frame = (bot_message.raw_data or {}).get("_wecom_frame") or {}
        try:
            from bot.dispatcher import get_dispatcher

            dispatcher = get_dispatcher()
            # 工作线程无运行中的事件循环，asyncio.run 起临时循环执行异步分发，
            # 与钉钉 Stream 的 dispatch_async 管线保持一致。
            response = asyncio.run(dispatcher.dispatch_async(bot_message))

            if response and response.text:
                self._reply_to_frame(frame, response.text)
        except Exception as exc:
            logger.error("[WeCom AI Bot] 异步处理消息失败: %s", exc)
            logger.exception(exc)

    # ------------------------------------------------------------------ #
    #  回复（aibot_respond_msg，透传回调 req_id）                          #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _generate_stream_id() -> str:
        return f"stream_{int(time.time() * 1000)}_{uuid.uuid4().hex[:8]}"

    def _reply_to_frame(self, frame: dict, text: str) -> bool:
        """向回调帧回复文本（默认一次性 markdown；可选 stream，finish=True）。

        长回复分片（r6 OR-COR-9d6c37af）：与主动推送（r5）共用同一
        切分器（``_split_wecom_aibot_text_chunks``，4000B 上限同源）——
        超限回复切分为多条 aibot_respond_msg 顺序发送（SDK 按 req_id 维护
        串行回复队列，多帧合法；stream 模式每片各成完整 stream）。每片
        独立经配额/并发闸记账（分片多消耗配额属预期，与主动路径口径
        一致）；同步分片失败 → 记日志含已发送片数并返回 False，已发出
        的帧不回滚（respond 帧无法撤回）。异步回执失败按发送标识退还
        每片串行等待回执完成（``future.result``，同 send_to_chat 语义）
        后才发送下一片；本片配额失败退还同步完成（r7）。
        """
        if not frame:
            logger.warning("[WeCom AI Bot] 无回调帧，无法回复")
            return False

        outbound_key = self._outbound_key_from_frame(frame)
        chunks = _split_wecom_aibot_text_chunks(text)
        if not chunks:
            logger.warning(
                "[WeCom AI Bot] 回复内容为空，跳过: key=%s", outbound_key
            )
            return False

        total = len(chunks)
        sent = 0
        for index, chunk in enumerate(chunks, start=1):
            part_label = f"{index}/{total}" if total > 1 else ""
            ok = self._reply_single_chunk(
                frame, chunk, outbound_key, part_label
            )
            if not ok:
                logger.error(
                    "[WeCom AI Bot] 回复分片 %d/%d 发送失败，本次回复整体失败"
                    "（已发送 %d/%d 帧，已发出帧不回滚）: key=%s",
                    index,
                    total,
                    sent,
                    total,
                    outbound_key,
                )
                return False
            sent = index
        if total > 1:
            logger.info(
                "[WeCom AI Bot] 长回复已按 %d 帧顺序发送完成: key=%s",
                total,
                outbound_key,
            )
        return True

    def _reply_single_chunk(
        self,
        frame: dict,
        text: str,
        outbound_key: str,
        part_label: str = "",
    ) -> bool:
        """发送单帧回复（≤4000B，已由调用方分片）——配额/并发闸/调度/
        异步回执处理的单元；分片循环见 :meth:`_reply_to_frame`。"""
        part_suffix = f"（{part_label}）" if part_label else ""

        token = self._acquire_outbound_slot(outbound_key)
        if token is None:
            return False

        # 会话级并发闸（r4 OR-COR-f5a96c8b）：被动回复与回推/静态推送共享
        # 同一传输层闸；闸满 → 退还本次配额并拒发（零虚耗）。
        outbound_gate_slot = _WECOM_AIBOT_OUTBOUND_GATE.try_acquire(outbound_key)
        if outbound_gate_slot is None:
            self._refund_outbound_send(outbound_key, token)
            logger.warning(
                "[WeCom AI Bot] 同会话并发超限（≤3 条在途），回复已丢弃"
                "（已退还配额）%s: key=%s",
                part_suffix,
                outbound_key,
            )
            return False

        if self._reply_stream_enabled:
            stream_id = self._generate_stream_id()
            coro = self.sdk_client.reply_stream(frame, stream_id, text, True)
        else:
            body = {"msgtype": "markdown", "markdown": {"content": text}}
            coro = self.sdk_client.reply(frame, body)

        try:
            future = self._schedule_reply(coro)
        except Exception as exc:
            outbound_gate_slot.release()
            self._refund_outbound_send(outbound_key, token)
            logger.error(
                "[WeCom AI Bot] 回复调度失败，已退还配额%s: key=%s, error=%s",
                part_suffix,
                outbound_key,
                exc,
            )
            return False

        if future is None:
            # 槽位检查后循环被清理：如实拒绝并退还本次扣量（r5）
            outbound_gate_slot.release()
            self._refund_outbound_send(outbound_key, token)
            logger.error(
                "[WeCom AI Bot] SDK 事件循环在调度时不可用（已退还配额）%s: key=%s",
                part_suffix,
                outbound_key,
            )
            return False

        # 串行等待回执完成（r7 OR-COR-82e5ad71）：同 send_to_chat 语义——
        # 槽位在回执完成后才释放，分片循环的下一片不再被自身并发闸截断
        # （12008B→4 片只发出 3 片的缺陷根因）。
        try:
            try:
                ack = future.result(self._reply_ack_timeout_seconds)
            except Exception as exc:
                self._refund_outbound_send(outbound_key, token)
                logger.error(
                    "[WeCom AI Bot] 回复发送失败（已退还配额）%s: key=%s, error=%s",
                    part_suffix,
                    outbound_key,
                    exc,
                )
                return False
            errcode = ack.get("errcode") if isinstance(ack, dict) else None
            if errcode:
                self._refund_outbound_send(outbound_key, token)
                logger.warning(
                    "[WeCom AI Bot] 回复被拒（已退还配额）%s: key=%s, errcode=%s, "
                    "errmsg=%s（官方前置条件：目标用户须先与机器人建过会话）",
                    part_suffix,
                    outbound_key,
                    errcode,
                    ack.get("errmsg") if isinstance(ack, dict) else None,
                )
                return False
            return True
        finally:
            outbound_gate_slot.release()

    def _schedule_reply(self, coro):
        """把回复协程调度到 SDK 事件循环（回复必须走持有 WebSocket 的循环）

        Returns:
            concurrent.futures.Future（异步发送回执），循环不可用时返回
            None（协程已关闭，调用方应如实按未发送处理）。
        """
        loop = self._loop
        if loop is None or loop.is_closed():
            logger.error("[WeCom AI Bot] 无法回复：SDK 事件循环不可用")
            coro.close()
            return None
        return asyncio.run_coroutine_threadsafe(coro, loop)

    def shutdown(self, wait: bool = False) -> None:
        """停止接受新消息并回收线程池"""
        self._shutdown = True
        with self._queue_lock:
            self._pending_messages.clear()
            self._active_conversations.clear()
        self._executor.shutdown(wait=wait)


class WecomAibotClient:
    """
    企微智能机器人长连接客户端

    类级默认 ``_authenticated_event = None``：__new__ 直接构造的测试客户端
    不做认证闸；正常 __init__ 路径会创建真实 Event 实例。

    封装官方 SDK WSClient：
    - 单后台线程运行（单机器人单连接互斥，防重连风暴——新连接订阅成功会踢掉
      旧连接，两条并发客户端会互相踢形成风暴）
    - 认证失败（aibot_subscribe errcode != 0）时适配器层指数退避重试
    - 30s 心跳与断线重连由 SDK 内置（heartbeat_interval=30000）
    """

    # 认证状态（r8 OR-COR-36f9842a）：authenticated 事件置位、周期重建/
    # 断线清除。类级默认 None = 无闸（__new__ 构造的测试客户端）。
    _authenticated_event: Optional[threading.Event] = None

    _AUTH_RETRY_BASE_DELAY_SECONDS = 2.0
    _AUTH_RETRY_MAX_DELAY_SECONDS = 30.0
    _AUTH_RETRY_MAX_ATTEMPTS = 5

    # 连接周期重建退避（SDK 重连预算耗尽/异常结束后重建新周期的等待）
    _CYCLE_RETRY_BASE_DELAY_SECONDS = 2.0
    _CYCLE_RETRY_MAX_DELAY_SECONDS = 60.0

    def __init__(
        self,
        bot_id: Optional[str] = None,
        secret: Optional[str] = None,
    ):
        if not WECOM_AIBOT_SDK_AVAILABLE:
            raise ImportError(
                "wecom-aibot-python-sdk SDK 未安装。\n"
                "请运行: pip install wecom-aibot-python-sdk"
            )

        config = get_config()

        self._bot_id = bot_id or getattr(config, "wecom_aibot_bot_id", None)
        self._secret = secret or getattr(config, "wecom_aibot_secret", None)

        if not self._bot_id or not self._secret:
            raise ValueError(
                "企微智能机器人长连接模式需要配置 WECOM_AIBOT_BOT_ID 和 WECOM_AIBOT_SECRET"
            )

        self._reply_stream_enabled = bool(
            getattr(config, "wecom_aibot_reply_stream", False)
        )

        self._authenticated_event = threading.Event()
        self._handler = WecomAibotHandler(reply_stream_enabled=self._reply_stream_enabled)
        self._handler._authenticated_event = self._authenticated_event
        self._sdk_client: Optional[Any] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._background_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._running = False

        # 认证失败退避状态（SDK 收到 errcode != 0 只上报不重试，重试在本层做）
        self._auth_failed = False
        self._planned_auth_delay: Optional[float] = None
        self._auth_attempts = 0
        self._auth_max_attempts = self._AUTH_RETRY_MAX_ATTEMPTS

        # 连接周期监督状态：SDK 内部重连预算耗尽后结束当前周期，由外层
        # 监督循环指数退避重建（预算随新周期重置），耗尽场景自愈
        self._cycle_failed = False
        self._planned_cycle_delay: Optional[float] = None
        self._cycle_attempts = 0

    # ------------------------------------------------------------------ #
    #  SDK 客户端与事件注册                                               #
    # ------------------------------------------------------------------ #

    def _create_sdk_client(self) -> Any:
        """创建 SDK 客户端（每轮连接新建实例，保证旧连接先被弃用）"""
        # 新周期从未认证状态起步（r8）：认证回执（authenticated 事件）
        # 到达后才置位，期间 wait_for_ready/发送路径均被闸住。
        self._authenticated_event.clear()
        sdk_client = WSClient(
            WSClientOptions(
                bot_id=self._bot_id,
                secret=self._secret,
                heartbeat_interval=30000,  # 官方建议 30s 心跳
            )
        )
        self._register_sdk_events(sdk_client)
        return sdk_client

    def _register_sdk_events(self, sdk_client: Any) -> None:
        """注册 SDK 事件处理器（独立方法，便于测试桩复用同一注册路径）"""
        self._handler.sdk_client = sdk_client

        @sdk_client.on("connected")
        def _on_connected():
            logger.info("[WeCom AI Bot] WebSocket 已连接，等待认证...")

        @sdk_client.on("authenticated")
        def _on_authenticated():
            self._on_authenticated()

        @sdk_client.on("disconnected")
        def _on_disconnected(reason):
            self._authenticated_event.clear()
            logger.warning("[WeCom AI Bot] 连接断开: %s", reason)

        @sdk_client.on("reconnecting")
        def _on_reconnecting(attempt):
            logger.info("[WeCom AI Bot] 第 %s 次重连...", attempt)

        @sdk_client.on("error")
        def _on_error(error):
            self._handle_auth_error(error)

        # Phase 1 最小闭环：仅订阅文本消息
        @sdk_client.on("message.text")
        def _on_text(frame):
            self._handler.handle_frame(frame)

    def _register_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """把当前事件循环共享给消息处理器（回复协程调度目标）"""
        self._loop = loop
        self._handler._loop = loop

    # ------------------------------------------------------------------ #
    #  认证失败降级（指数退避）与连接周期监督（预算耗尽自愈）              #
    # ------------------------------------------------------------------ #

    @classmethod
    def _auth_backoff_delay(cls, attempt: int) -> float:
        """指数退避：2s → 4s → 8s → 16s → 30s（封顶）"""
        return min(
            cls._AUTH_RETRY_BASE_DELAY_SECONDS * (2 ** (attempt - 1)),
            cls._AUTH_RETRY_MAX_DELAY_SECONDS,
        )

    def _next_auth_retry_delay(self) -> Optional[float]:
        """消费一次认证重试预算；超出上限返回 None（放弃）"""
        self._auth_attempts += 1
        if self._auth_attempts > self._auth_max_attempts:
            return None
        return self._auth_backoff_delay(self._auth_attempts)

    def _next_cycle_retry_delay(self) -> float:
        """连接周期重建退避（指数递增、封顶、永不放弃——耗尽场景必须自愈）"""
        self._cycle_attempts += 1
        return min(
            self._CYCLE_RETRY_BASE_DELAY_SECONDS * (2 ** (self._cycle_attempts - 1)),
            self._CYCLE_RETRY_MAX_DELAY_SECONDS,
        )

    def _on_authenticated(self) -> None:
        """认证成功：置位认证事件、复位认证与连接周期退避预算"""
        self._authenticated_event.set()
        self._auth_attempts = 0
        self._auth_failed = False
        self._planned_auth_delay = None
        self._cycle_failed = False
        self._planned_cycle_delay = None
        self._cycle_attempts = 0
        logger.info("[WeCom AI Bot] 认证成功（aibot_subscribe errcode=0），开始收消息")

    def _handle_auth_error(self, error: BaseException) -> None:
        """SDK error 事件入口：按错误类别分流（认证失败 / 重连预算耗尽 / 其他）"""
        message = str(error or "")

        # SDK 重连预算耗尽（"Max reconnect attempts exceeded"）：SDK 内部放弃
        # 后 run_forever 会永久空转（线程活着却永不重连）。必须结束当前连接
        # 周期，让外层监督循环在退避后重建全新周期（新 SDK 实例重置其内部
        # 重连预算），实现耗尽自愈，无需人工重启进程（OR-COR-a12b0edd）。
        if "Max reconnect attempts exceeded" in message:
            self._cycle_failed = True
            self._planned_cycle_delay = self._next_cycle_retry_delay()
            logger.warning(
                "[WeCom AI Bot] SDK 重连预算耗尽（%s），%.1f 秒后由监督循环"
                "重建连接周期（第 %s 次）",
                message,
                self._planned_cycle_delay,
                self._cycle_attempts,
            )
            self._request_loop_stop()
            return

        if "Authentication failed" not in message:
            logger.error("[WeCom AI Bot] 运行错误: %s", message)
            return

        self._auth_failed = True
        delay = self._next_auth_retry_delay()
        if delay is None:
            logger.error(
                "[WeCom AI Bot] 认证连续失败 %s 次，放弃重试（give up）。"
                "请检查 WECOM_AIBOT_BOT_ID / WECOM_AIBOT_SECRET 配置。",
                self._auth_attempts,
            )
            self._running = False
            self._planned_auth_delay = None
        else:
            self._planned_auth_delay = delay
            logger.warning(
                "[WeCom AI Bot] 认证失败（%s），%.1f 秒后重试（第 %s/%s 次）",
                message,
                delay,
                self._auth_attempts,
                self._auth_max_attempts,
            )
        self._request_loop_stop()

    def _request_loop_stop(self) -> None:
        """请求停止当前事件循环（线程安全）"""
        loop = self._loop
        if loop is not None and not loop.is_closed():
            try:
                loop.call_soon_threadsafe(loop.stop)
            except RuntimeError:
                pass

    # ------------------------------------------------------------------ #
    #  生命周期                                                           #
    # ------------------------------------------------------------------ #

    def start_background(self) -> bool:
        """在后台线程启动客户端；已有存活线程时拒绝（单连接互斥）"""
        if not WECOM_AIBOT_SDK_AVAILABLE:
            logger.warning("[WeCom AI Bot] SDK 未安装，无法启动")
            logger.warning("[WeCom AI Bot] 请运行: pip install wecom-aibot-python-sdk")
            return False

        if self._background_thread and self._background_thread.is_alive():
            logger.warning(
                "[WeCom AI Bot] 客户端已在运行，拒绝重复启动（单机器人单连接互斥）"
            )
            return False

        self._running = True
        self._stop_event.clear()
        self._background_thread = threading.Thread(
            target=self._run_background,
            daemon=True,
            name="WecomAibotClient",
        )
        self._background_thread.start()
        logger.info("[WeCom AI Bot] 后台客户端已启动")
        return True

    def _run_background(self) -> None:
        """后台监督主循环：一轮 = 一个事件循环 + 一个 SDK 客户端实例

        连接周期以任何原因结束（网络断开、SDK 重连预算耗尽、异常、外部
        stop 之外的情况）后，监督循环退避等待并重建全新周期——新 SDK 实例
        自带重置的内部重连预算，耗尽场景自愈，无需人工重启进程
        （OR-COR-a12b0edd）。
        """
        while self._running:
            self._auth_failed = False
            self._planned_auth_delay = None
            self._cycle_failed = False
            self._planned_cycle_delay = None

            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            self._register_loop(loop)
            self._sdk_client = self._create_sdk_client()

            try:
                loop.run_until_complete(self._sdk_client.connect())
                if not self._auth_failed and not self._cycle_failed:
                    loop.run_forever()
            except Exception as exc:
                logger.error("[WeCom AI Bot] 运行异常: %s", exc)
            finally:
                self._teardown_cycle(loop)

            if not self._running:
                break

            if self._auth_failed:
                delay = self._planned_auth_delay
                if delay is None:
                    break  # 已在 _handle_auth_error 记录放弃并置 _running=False
                logger.warning(
                    "[WeCom AI Bot] 将在 %.1f 秒后重建连接并重新认证", delay
                )
                if self._stop_event.wait(delay):
                    break
                continue

            # 非认证原因结束的连接周期（SDK 重连预算耗尽、网络断开、异常等）
            delay = (
                self._planned_cycle_delay
                if self._cycle_failed
                else self._next_cycle_retry_delay()
            )
            logger.info(
                "[WeCom AI Bot] 连接周期结束，%.1f 秒后重建连接周期"
                "（第 %s 次周期重建）",
                delay,
                self._cycle_attempts,
            )
            if self._stop_event.wait(delay):
                break

    def _teardown_cycle(self, loop: asyncio.AbstractEventLoop) -> None:
        """收尾一轮连接：断开 SDK 客户端并关闭事件循环"""
        try:
            if self._sdk_client is not None:
                self._sdk_client.disconnect()
        except Exception as exc:
            logger.debug("[WeCom AI Bot] 断开 SDK 客户端异常: %s", exc)

        try:
            # 给 SDK 内部排队的清理协程一个执行窗口
            loop.run_until_complete(asyncio.sleep(0.1))
            loop.run_until_complete(loop.shutdown_asyncgens())
        except Exception:
            pass
        finally:
            try:
                loop.close()
            except Exception:
                pass
            asyncio.set_event_loop(None)
            self._loop = None
            self._handler._loop = None

    def _send_single_to_chat(
        self,
        chatid: str,
        text: str,
        timeout_seconds: float,
        part_label: str = "",
    ) -> bool:
        """发送单条 markdown（≤4000B，已由调用方分片）——配额/并发闸/回执
        处理的单元；分片循环见 :meth:`send_to_chat`。

        语义承袭（r3/r4/r5）：可用性前置（配额临界区内、扣量之前检查，
        不可用直接拒绝且零记账）；发送失败回滚（future 异常/超时或服务端
        errcode != 0 时按发送标识精确退还本次双窗口扣量）；官方前置条件
        （目标用户须先与机器人建过会话）在 errcode != 0 的日志中标注。
        """
        part_suffix = f"（{part_label}）" if part_label else ""

        conversation_key = chatid or "unknown"
        handler = self._handler

        # 配额 + 可用性判定（同一临界区，r3 原子语义 + r4 可用性前置；
        # r5：记录携带发送标识 token，失败按标识精确退还）
        with handler._outbound_quota_lock:
            if not handler._outbound_minute_limiter.would_allow(conversation_key):
                logger.warning(
                    "[WeCom AI Bot] 会话推送超限（分钟30条或小时1000条配额），"
                    "消息已丢弃%s: key=%s",
                    part_suffix,
                    conversation_key,
                )
                return False
            if not handler._outbound_hour_limiter.would_allow(conversation_key):
                logger.warning(
                    "[WeCom AI Bot] 会话推送超限（分钟30条或小时1000条配额），"
                    "消息已丢弃: key=%s",
                    conversation_key,
                )
                return False
            # 认证闸（r8 OR-COR-36f9842a）：TCP 已连但认证回执未到（连接中/
            # 重连中）→ 拒发零记账，一次性 CLI 任务不丢报告。
            auth_event = getattr(self, "_authenticated_event", None)
            if auth_event is not None and not auth_event.is_set():
                logger.warning(
                    "[WeCom AI Bot] 长连接未完成认证（连接中/重连中），"
                    "消息已丢弃（零记账）%s: key=%s",
                    part_suffix,
                    conversation_key,
                )
                return False
            if not self._running or self._sdk_client is None:
                logger.warning(
                    "[WeCom AI Bot] 长连接客户端未运行，无法主动推送: key=%s",
                    conversation_key,
                )
                return False  # 零记账
            loop = self._loop
            if loop is None or loop.is_closed():
                logger.error("[WeCom AI Bot] 无法主动推送：SDK 事件循环不可用")
                return False  # 零记账
            # 会话级并发闸（r4 OR-COR-f5a96c8b）：与回复/回推路径共享同一
            # 传输层闸，混合叠加也不超同会话并发 ≤3；拒绝零记账。
            # （置于全部纯检查之后，杜绝检查分支上的槽位泄漏）
            outbound_gate_slot = _WECOM_AIBOT_OUTBOUND_GATE.try_acquire(
                conversation_key
            )
            if outbound_gate_slot is None:
                logger.warning(
                    "[WeCom AI Bot] 同会话并发超限（≤3 条在途），消息已丢弃"
                    "（零记账）%s: key=%s",
                    part_suffix,
                    conversation_key,
                )
                return False
            send_token = uuid.uuid4().hex
            handler._outbound_minute_limiter.record(
                conversation_key, token=send_token
            )
            handler._outbound_hour_limiter.record(
                conversation_key, token=send_token
            )

        body = {"msgtype": "markdown", "markdown": {"content": text}}
        try:
            try:
                ack = asyncio.run_coroutine_threadsafe(
                    self._sdk_client.send_message(chatid, body), loop
                ).result(timeout_seconds)
            except Exception as exc:
                handler._refund_outbound_send(conversation_key, send_token)
                logger.error(
                    "[WeCom AI Bot] 主动推送失败（已退还配额）%s: key=%s, error=%s",
                    part_suffix,
                    conversation_key,
                    exc,
                )
                return False

            errcode = ack.get("errcode") if isinstance(ack, dict) else None
            if errcode:
                handler._refund_outbound_send(conversation_key, send_token)
                logger.warning(
                    "[WeCom AI Bot] 主动推送被拒（已退还配额）%s: key=%s, errcode=%s, "
                    "errmsg=%s（官方前置条件：目标用户须先与机器人建过会话）",
                    part_suffix,
                    conversation_key,
                    errcode,
                    ack.get("errmsg") if isinstance(ack, dict) else None,
                )
                return False
            return True
        finally:
            # 发送完成（回执到达，无论成败）即释放并发槽（r4）
            outbound_gate_slot.release()

    def send_to_chat(self, chatid: str, text: str, timeout_seconds: float = 15.0) -> bool:
        """向指定会话推送 markdown 消息（aibot_send_msg，同步等待回执）。

        静态推送渠道与来源会话回推（source-context 报告返回）的共享咽喉点。

        - 长报告分片（r5 OR-COR-7ab3e812）：内容 UTF-8 字节数超过
          notification_capabilities 声明的渠道上限（wecom_aibot
          max_text_bytes=4000）时，按段落/行边界优先切分（字节安全兜底，
          绝不切开多字节字符），顺序发送各片——**每片独立经限流、并发闸
          与双窗口配额记账（分片会多消耗配额，属预期行为）**；任一片失败
          → 整体返回 False，日志记录已发送片数（部分交付可观测）。
        - ≤上限的内容原样单条发送（与 r5 之前路径零差异）。
        - 其余语义（可用性前置、失败回滚、官方前置条件标注、幂等并发槽）
          与 r4 版本一致，见 :meth:`_send_single_to_chat`。

        Returns:
            是否全部发送成功（分片时任一片失败即为 False）
        """
        chunks = _split_wecom_aibot_text_chunks(text)
        if not chunks:
            logger.warning(
                "[WeCom AI Bot] 推送内容为空，跳过: key=%s",
                chatid or "unknown",
            )
            return False
        total = len(chunks)
        sent = 0
        for index, chunk in enumerate(chunks, start=1):
            part_label = f"{index}/{total}" if total > 1 else ""
            ok = self._send_single_to_chat(chatid, chunk, timeout_seconds, part_label)
            if not ok:
                logger.error(
                    "[WeCom AI Bot] 报告分片 %d/%d 发送失败，本次推送整体失败"
                    "（已发送 %d/%d 片，部分交付）: key=%s",
                    index,
                    total,
                    sent,
                    total,
                    chatid or "unknown",
                )
                return False
            sent = index
        if total > 1:
            logger.info(
                "[WeCom AI Bot] 长报告已按 %d 片顺序发送完成: key=%s",
                total,
                chatid or "unknown",
            )
        return True

    def stop(self) -> None:
        """停止客户端"""
        self._running = False
        self._stop_event.set()
        self._request_loop_stop()
        self._handler.shutdown(wait=False)
        thread = self._background_thread
        if thread and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=5)
        logger.info("[WeCom AI Bot] 客户端已停止")

    @property
    def is_running(self) -> bool:
        return self._running

    def wait_for_ready(
        self,
        timeout_seconds: float = 10.0,
        poll_interval: float = 0.2,
    ) -> bool:
        """等待长连接就绪（r7 惰性启动预算，OR-COR-b365f904）。

        就绪判定：监督循环在运行且 SDK 客户端已连接（认证成功后
        ``sdk_client.is_connected`` 为真）。超时返回 False——调用方本次
        推送降级失败，下次发送再试（start_background 幂等，不会重复启动）。
        stop 事件置位时立即返回 False（进程退出路径不被拖住）。
        """
        deadline = time.time() + timeout_seconds
        while True:
            sdk_client = self._sdk_client
            auth_event = getattr(self, "_authenticated_event", None)
            if (
                self._running
                and sdk_client is not None
                and bool(getattr(sdk_client, "is_connected", False))
                and (auth_event is None or auth_event.is_set())
            ):
                return True
            remaining = deadline - time.time()
            if remaining <= 0:
                return False
            if self._stop_event.wait(min(poll_interval, remaining)):
                return False

    def is_transport_ready(self) -> bool:
        """诊断/测试用：连接是否已就绪（运行中且 SDK 已连接且已认证）。"""
        return self._is_transport_ready()

    def _is_transport_ready(self) -> bool:
        sdk_client = self._sdk_client
        auth_event = getattr(self, "_authenticated_event", None)
        return bool(
            self._running
            and sdk_client is not None
            and getattr(sdk_client, "is_connected", False)
            and (auth_event is None or auth_event.is_set())
        )


# 全局客户端实例（单例，进一步保证单机器人单连接）
_wecom_aibot_client: Optional[WecomAibotClient] = None
_wecom_aibot_client_lock = threading.Lock()


def _reset_wecom_aibot_client() -> None:
    """重置全局客户端（仅测试用）"""
    global _wecom_aibot_client
    with _wecom_aibot_client_lock:
        _wecom_aibot_client = None


def get_wecom_aibot_client() -> Optional[WecomAibotClient]:
    """获取全局客户端实例（未配置时返回 None，不产生副作用）"""
    global _wecom_aibot_client
    with _wecom_aibot_client_lock:
        if _wecom_aibot_client is None:
            if not WECOM_AIBOT_SDK_AVAILABLE:
                logger.warning(
                    "[WeCom AI Bot] wecom-aibot-python-sdk SDK 未安装，长连接模式不可用"
                )
                logger.warning(
                    "[WeCom AI Bot] 请运行: pip install wecom-aibot-python-sdk"
                )
                return None
            try:
                _wecom_aibot_client = WecomAibotClient()
            except (ImportError, ValueError) as exc:
                logger.warning("[WeCom AI Bot] 无法创建客户端: %s", exc)
                return None
        return _wecom_aibot_client


def start_wecom_aibot_background() -> bool:
    """在后台启动企微智能机器人长连接客户端

    Returns:
        是否成功启动（未启用 / 缺凭证 / 缺 SDK 均为 False，零副作用）
    """
    if not WECOM_AIBOT_SDK_AVAILABLE:
        logger.warning("[WeCom AI Bot] SDK 未安装，无法启动长连接客户端")
        logger.warning("[WeCom AI Bot] 请运行: pip install wecom-aibot-python-sdk")
        return False

    config = get_config()

    if not getattr(config, "wecom_aibot_enabled", False):
        logger.debug("[WeCom AI Bot] WECOM_AIBOT_ENABLED 未开启，跳过启动")
        return False

    client = get_wecom_aibot_client()
    if client:
        return client.start_background()
    return False
