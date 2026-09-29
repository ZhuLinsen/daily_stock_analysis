# -*- coding: utf-8 -*-
"""
History command — view recent Agent conversation sessions.

**User isolation**: each user can only see sessions whose ``session_id``
starts with their own ``{platform}_{user_id}`` prefix.
"""

import logging
from typing import List, Optional

from bot.commands.base import BotCommand
from bot.models import BotMessage, BotResponse, ChatType

logger = logging.getLogger(__name__)


def _user_prefix(message: BotMessage) -> str:
    """Canonical session-id prefix for a given user.

    Session IDs follow the pattern ``{platform}_{user_id}:{scope}``.
    The colon delimiter prevents prefix-collision between user IDs
    (e.g. user '123' vs '1234').
    """
    return f"{message.platform}_{message.user_id}:"


def _legacy_chat_session_id(message: BotMessage) -> str:
    """Legacy chat session id used before the colon-scoped format."""
    return f"{message.platform}_{message.user_id}"


def _current_chat_session_id(message: BotMessage) -> str:
    """Current chat session id for the active conversation scope."""
    prefix = _user_prefix(message)
    if message.chat_type == ChatType.GROUP and message.chat_id:
        return f"{prefix}{message.chat_id}:chat"
    return f"{prefix}chat"


class HistoryCommand(BotCommand):
    """
    View recent agent conversation history (scoped to current user).

    Usage:
        /history          - List your recent sessions
        /history <id>     - View messages in one of your sessions
        /history clear    - Clear your current session
    """

    @property
    def name(self) -> str:
        return "history"

    @property
    def aliases(self) -> List[str]:
        return ["历史", "会话"]

    @property
    def description(self) -> str:
        return "查看 Agent 对话历史"

    @property
    def usage(self) -> str:
        return "/history [session_id | clear]"

    def execute(self, message: BotMessage, args: List[str]) -> BotResponse:
        """Execute the history command."""
        try:
            from src.storage import get_db
            db = get_db()
        except Exception as e:
            logger.error(f"History: storage unavailable: {e}")
            return BotResponse.text_response("⚠️ 存储模块不可用，无法查询对话历史。")

        prefix = _user_prefix(message)
        legacy_chat_session_id = _legacy_chat_session_id(message)
        current_chat_session_id = _current_chat_session_id(message)

        # /history clear — clear current user's chat session
        if args and args[0].lower() in ("clear", "清除"):
            try:
                deleted = db.delete_conversation_session(current_chat_session_id)
                if current_chat_session_id == f"{prefix}chat":
                    deleted += db.delete_conversation_session(legacy_chat_session_id)
                return BotResponse.text_response(
                    f"✅ 已清除当前会话 ({deleted} 条消息)"
                )
            except Exception as e:
                logger.error(f"History clear failed: {e}")
                return BotResponse.text_response(f"⚠️ 清除失败: {str(e)}")

        # /history <session_id> — show messages for a specific session
        # Only allow access if the session belongs to the requesting user.
        if args and not args[0].isdigit():
            session_id = args[0]
            if not (session_id.startswith(prefix) or session_id == legacy_chat_session_id):
                return BotResponse.text_response("⚠️ 你只能查看自己的会话记录。")
            try:
                messages_list = db.get_conversation_messages(session_id, limit=20)
                if not messages_list:
                    return BotResponse.text_response(f"📭 会话 `{session_id}` 无消息记录")

                lines = [f"💬 **会话详情**: `{session_id}`", ""]
                for msg in messages_list:
                    role_icon = "👤" if msg["role"] == "user" else "🤖"
                    content_preview = msg["content"][:200]
                    if len(msg["content"]) > 200:
                        content_preview += "..."
                    time_str = msg.get("created_at", "")[:16] if msg.get("created_at") else ""
                    lines.append(f"{role_icon} {time_str}")
                    lines.append(f"  {content_preview}")
                    lines.append("")

                return BotResponse.markdown_response("\n".join(lines))
            except Exception as e:
                logger.error(f"History detail failed: {e}")
                return BotResponse.text_response(f"⚠️ 获取会话详情失败: {str(e)}")

        # /history [count] — list recent sessions for this user only
        limit = 10
        if args and args[0].isdigit():
            limit = min(int(args[0]), 50)

        try:
            sessions = db.get_chat_sessions(
                limit=limit,
                session_prefix=prefix,
                extra_session_ids=[legacy_chat_session_id],
            )
            if not sessions:
                return BotResponse.text_response("📭 暂无对话历史记录")

            lines = ["📋 **最近对话会话**", ""]
            for i, sess in enumerate(sessions, 1):
                title = sess.get("title", "新对话")
                msg_count = sess.get("message_count", 0)
                last_active = sess.get("last_active", "")[:16] if sess.get("last_active") else ""
                sid = sess["session_id"]
                lines.append(f"**{i}.** {title}")
                lines.append(f"   💬 {msg_count} 条消息 | 🕐 {last_active}")
                lines.append(f"   ID: `{sid}`")
                lines.append("")

            lines.append(f"💡 使用 `/history <session_id>` 查看具体会话内容")
            return BotResponse.markdown_response("\n".join(lines))

        except Exception as e:
            logger.error(f"History list failed: {e}")
            return BotResponse.text_response(f"⚠️ 获取会话列表失败: {str(e)}")
