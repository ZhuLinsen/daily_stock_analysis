import pytest

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


class _FakeDomainConfig:
    """Minimal config stand-in exposing only ``feishu_domain``."""

    def __init__(self, domain: str = "feishu"):
        self.feishu_domain = domain


def test_resolve_lark_domain_defaults_to_feishu():
    lark = pytest.importorskip("lark_oapi")
    from bot.platforms.feishu_stream import _resolve_lark_domain

    assert _resolve_lark_domain(_FakeDomainConfig()) == lark.FEISHU_DOMAIN


def test_resolve_lark_domain_maps_lark_to_larksuite():
    lark = pytest.importorskip("lark_oapi")
    from bot.platforms.feishu_stream import _resolve_lark_domain

    assert _resolve_lark_domain(_FakeDomainConfig(domain="lark")) == lark.LARK_DOMAIN


def test_resolve_lark_domain_invalid_value_falls_back_to_feishu():
    lark = pytest.importorskip("lark_oapi")
    from bot.platforms.feishu_stream import _resolve_lark_domain

    assert _resolve_lark_domain(_FakeDomainConfig(domain="not-a-domain")) == lark.FEISHU_DOMAIN


def test_stream_client_uses_lark_domain_when_configured(monkeypatch):
    lark = pytest.importorskip("lark_oapi")
    from bot.platforms.feishu_stream import FeishuStreamClient

    # Patch the module-level binding both clients resolve via, so the fake
    # config is guaranteed to reach FeishuStreamClient (not the real config).
    monkeypatch.setattr(
        "bot.platforms.feishu_stream.get_config",
        lambda: _FakeDomainConfig(domain="lark"),
    )

    client = FeishuStreamClient(app_id="cli_xxx", app_secret="secret")

    # Regression for issue #937: Stream mode must honour FEISHU_DOMAIN=lark
    # so international Lark users do not hit "Incorrect domain name".
    assert client._domain == lark.LARK_DOMAIN


def test_stream_start_passes_lark_domain_to_ws_client(monkeypatch):
    # Covers the runtime path reviewer flagged: start() must actually pass the
    # resolved domain into lark-oapi's ws.Client, not only store it on _domain.
    lark = pytest.importorskip("lark_oapi")
    from bot.platforms import feishu_stream

    monkeypatch.setattr(
        "bot.platforms.feishu_stream.get_config",
        lambda: _FakeDomainConfig(domain="lark"),
    )

    captured = {}

    class _FakeWSClient:
        def __init__(self, **kwargs):
            captured["kwargs"] = kwargs

        def start(self):
            captured["started"] = True

    monkeypatch.setattr(feishu_stream.ws, "Client", _FakeWSClient)

    client = feishu_stream.FeishuStreamClient(app_id="cli_xxx", app_secret="secret")
    client.start()

    assert captured.get("started") is True
    assert captured["kwargs"].get("domain") == lark.LARK_DOMAIN
