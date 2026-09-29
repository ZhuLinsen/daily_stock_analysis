# -*- coding: utf-8 -*-
"""Unit tests for Feishu Stream message ordering guarantees."""

import threading
import time
import unittest
from datetime import datetime

from bot.models import BotMessage, BotResponse, ChatType
from bot.platforms.feishu_stream import FeishuStreamHandler


class _DummyReplyClient:
    def __init__(self):
        self.calls = []
        self._lock = threading.Lock()

    def reply_text(self, message_id, text, at_user=False, user_id=None):
        with self._lock:
            self.calls.append(
                {
                    "message_id": message_id,
                    "text": text,
                    "at_user": at_user,
                    "user_id": user_id,
                }
            )
        return True


def _make_message(
    message_id: str,
    *,
    user_id: str = "u1",
    chat_id: str = "c1",
    chat_type: ChatType = ChatType.PRIVATE,
) -> BotMessage:
    return BotMessage(
        platform="feishu",
        message_id=message_id,
        user_id=user_id,
        user_name=user_id,
        chat_id=chat_id,
        chat_type=chat_type,
        content="/chat hello",
        raw_content="/chat hello",
        mentioned=True,
        timestamp=datetime.now(),
    )


class FeishuStreamOrderingTestCase(unittest.TestCase):
    def test_same_conversation_is_processed_fifo(self):
        reply_client = _DummyReplyClient()
        processed = []

        def on_message(message: BotMessage) -> BotResponse:
            if message.message_id == "m1":
                time.sleep(0.05)
            processed.append(message.message_id)
            return BotResponse.text_response(message.message_id)

        handler = FeishuStreamHandler(on_message, reply_client)
        try:
            handler._enqueue_message(_make_message("m1"))
            handler._enqueue_message(_make_message("m2"))

            deadline = time.time() + 1.0
            while len(reply_client.calls) < 2 and time.time() < deadline:
                time.sleep(0.01)

            self.assertEqual(processed, ["m1", "m2"])
            self.assertEqual(
                [call["message_id"] for call in reply_client.calls],
                ["m1", "m2"],
            )
        finally:
            handler.shutdown(wait=True)

    def test_group_chat_uses_user_scoped_ordering_key(self):
        handler = FeishuStreamHandler(lambda _message: BotResponse.text_response("ok"), _DummyReplyClient())
        try:
            key_a = handler._conversation_key(
                _make_message("m1", user_id="u1", chat_id="group-1", chat_type=ChatType.GROUP)
            )
            key_b = handler._conversation_key(
                _make_message("m2", user_id="u2", chat_id="group-1", chat_type=ChatType.GROUP)
            )

            self.assertEqual(key_a, "group-1:u1")
            self.assertEqual(key_b, "group-1:u2")
            self.assertNotEqual(key_a, key_b)
        finally:
            handler.shutdown(wait=True)


if __name__ == "__main__":
    unittest.main()
