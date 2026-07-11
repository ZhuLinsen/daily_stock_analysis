from bot.platforms.feishu_stream import FeishuReplyClient
from src.formatters import format_feishu_markdown


class DummyFeishuReplyClient(FeishuReplyClient):
    def __init__(self, max_bytes: int = 1000):
        # Bypass parent init to avoid SDK dependency
        self._max_bytes = max_bytes
        self.calls = []

    def _send_interactive_card(
        self,
        content: str,
        message_id: str | None = None,
        chat_id: str | None = None,
        receive_id_type: str = "chat_id",
        at_user: bool = False,
        user_id: str | None = None,
    ) -> bool:
        self.calls.append(
            {
                "content": content,
                "message_id": message_id,
                "chat_id": chat_id,
                "receive_id_type": receive_id_type,
                "at_user": at_user,
                "user_id": user_id,
            }
        )
        return True


def test_reply_text_chunked_keeps_reply_and_at_user(monkeypatch):
    client = DummyFeishuReplyClient(max_bytes=1000)

    message_id = "msg_123"
    user_id = "user_456"
    text = "A" * 3000  # longer than max_bytes so it will be chunked

    result = client.reply_text(message_id=message_id, text=text, at_user=True, user_id=user_id)

    assert result is True
    # Should produce multiple chunks
    assert len(client.calls) >= 2

    for call in client.calls:
        assert call["message_id"] == message_id
        assert call["chat_id"] is None
        assert call["at_user"] is True
        assert call["user_id"] == user_id


def test_reply_text_uses_legacy_feishu_markdown_formatter():
    client = DummyFeishuReplyClient(max_bytes=1000)
    text = "# 日报\n\n## 📊 分析结果摘要\n\n| 股票 | 信号 |\n| --- | --- |\n| 600519 | 强势 |"

    result = client.reply_text(message_id="msg_123", text=text)

    assert result is True
    assert client.calls[0]["content"] == format_feishu_markdown(text)


def test_send_to_chat_chunked_uses_chat_id(monkeypatch):
    client = DummyFeishuReplyClient(max_bytes=1000)

    chat_id = "chat_123"
    text = "B" * 3000  # longer than max_bytes so it will be chunked

    result = client.send_to_chat(chat_id=chat_id, text=text, receive_id_type="chat_id")

    assert result is True
    assert len(client.calls) >= 2

    for call in client.calls:
        assert call["message_id"] is None
        assert call["chat_id"] == chat_id
        assert call["receive_id_type"] == "chat_id"
        assert call["at_user"] is False
        assert call["user_id"] is None


def test_send_to_chat_uses_legacy_feishu_markdown_formatter():
    client = DummyFeishuReplyClient(max_bytes=1000)
    text = "# 日报\n\n[详情](https://example.com/report)"

    result = client.send_to_chat(chat_id="chat_123", text=text)

    assert result is True
    assert client.calls[0]["content"] == format_feishu_markdown(text)
