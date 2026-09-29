from unittest import mock

import bot.platforms.feishu_stream as feishu_stream
from bot.platforms.feishu_stream import (
    FEISHU_DOMAIN,
    LARK_DOMAIN,
    FeishuReplyClient,
    FeishuStreamClient,
)
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


def test_reply_client_uses_lark_domain_from_config():
    builder = mock.MagicMock()
    builder.app_id.return_value = builder
    builder.app_secret.return_value = builder
    builder.domain.return_value = builder
    builder.log_level.return_value = builder

    config = mock.Mock(feishu_domain="lark", feishu_max_bytes=20000)
    with mock.patch.object(feishu_stream, "FEISHU_SDK_AVAILABLE", True), \
            mock.patch.object(feishu_stream, "get_config", return_value=config), \
            mock.patch.object(feishu_stream, "lark", create=True) as lark:
        lark.Client.builder.return_value = builder
        FeishuReplyClient("cli_test", "secret")

    builder.domain.assert_called_once_with(LARK_DOMAIN)


def test_stream_and_reply_clients_share_lark_domain():
    config = mock.Mock(
        feishu_app_id="cli_test",
        feishu_app_secret="secret",
        feishu_domain="lark",
    )
    reply_client = mock.Mock()
    ws_client = mock.Mock()

    with mock.patch.object(feishu_stream, "FEISHU_SDK_AVAILABLE", True), \
            mock.patch("src.config.get_config", return_value=config), \
            mock.patch.object(
                feishu_stream,
                "FeishuReplyClient",
                return_value=reply_client,
            ) as reply_client_class, \
            mock.patch.object(feishu_stream, "ws", create=True) as ws, \
            mock.patch.object(feishu_stream, "lark", create=True) as lark:
        ws.Client.return_value = ws_client
        client = FeishuStreamClient()
        with mock.patch.object(client, "_create_event_handler", return_value=mock.Mock()):
            client.start()

    ws.Client.assert_called_once_with(
        app_id="cli_test",
        app_secret="secret",
        event_handler=mock.ANY,
        domain=LARK_DOMAIN,
        log_level=lark.LogLevel.WARNING,
        auto_reconnect=True,
    )
    reply_client_class.assert_not_called()
    ws_client.start.assert_called_once_with()

    with mock.patch.object(feishu_stream, "FeishuReplyClient") as reply_client_class:
        client._create_message_handler = mock.Mock(return_value=mock.Mock())
        with mock.patch.object(feishu_stream, "FeishuStreamHandler"), \
                mock.patch.object(feishu_stream, "lark", create=True):
            client._create_event_handler()

    reply_client_class.assert_called_once_with(
        "cli_test",
        "secret",
        domain=LARK_DOMAIN,
    )


def test_invalid_stream_domain_falls_back_to_feishu(caplog):
    assert feishu_stream._resolve_feishu_domain("invalid") == FEISHU_DOMAIN
    assert "回退为 feishu" in caplog.text


def test_reply_text_chunked_keeps_reply_and_at_user(monkeypatch):
    sleep_calls = []
    monkeypatch.setattr(
        "bot.platforms.feishu_stream.time.sleep",
        lambda seconds: sleep_calls.append(seconds),
    )
    client = DummyFeishuReplyClient(max_bytes=1000)

    message_id = "msg_123"
    user_id = "user_456"
    text = "A" * 3000  # longer than max_bytes so it will be chunked

    result = client.reply_text(message_id=message_id, text=text, at_user=True, user_id=user_id)

    assert result is True
    # Should produce multiple chunks
    assert len(client.calls) >= 2
    assert sleep_calls == [1] * (len(client.calls) - 1)

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
    sleep_calls = []
    monkeypatch.setattr(
        "bot.platforms.feishu_stream.time.sleep",
        lambda seconds: sleep_calls.append(seconds),
    )
    client = DummyFeishuReplyClient(max_bytes=1000)

    chat_id = "chat_123"
    text = "B" * 3000  # longer than max_bytes so it will be chunked

    result = client.send_to_chat(chat_id=chat_id, text=text, receive_id_type="chat_id")

    assert result is True
    assert len(client.calls) >= 2
    assert sleep_calls == [1] * (len(client.calls) - 1)

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
