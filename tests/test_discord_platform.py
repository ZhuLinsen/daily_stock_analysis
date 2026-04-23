# -*- coding: utf-8 -*-
import json
import time
from types import SimpleNamespace
from unittest.mock import patch

from nacl.signing import SigningKey

from bot.models import ChatType
from bot.platforms.discord import DiscordPlatform


def _make_platform(public_key: str) -> DiscordPlatform:
    with patch(
        "src.config.get_config",
        return_value=SimpleNamespace(
            discord_interactions_public_key=public_key,
        ),
    ):
        return DiscordPlatform()


def _current_timestamp() -> str:
    """返回当前 Unix 秒字符串，用于生成有效签名。"""
    return str(int(time.time()))


def _sign_headers(signing_key: SigningKey, body: bytes, timestamp: str | None = None):
    if timestamp is None:
        timestamp = _current_timestamp()
    signature = signing_key.sign(timestamp.encode("utf-8") + body).signature.hex()
    return {
        "X-Signature-Ed25519": signature,
        "X-Signature-Timestamp": timestamp,
    }


def test_signed_ping_request_is_accepted():
    signing_key = SigningKey.generate()
    platform = _make_platform(signing_key.verify_key.encode().hex())
    payload = {"type": 1}
    body = json.dumps(payload).encode("utf-8")

    message, response = platform.handle_webhook(
        _sign_headers(signing_key, body),
        body,
        payload,
    )

    assert message is None
    assert response is not None
    assert response.status_code == 200
    assert response.body == {"type": 1}


def test_signed_interaction_request_returns_deferred_ack():
    """type=2 交互应返回 type 5 延迟 ACK，同时仍解析出 BotMessage。"""
    signing_key = SigningKey.generate()
    platform = _make_platform(signing_key.verify_key.encode().hex())
    payload = {
        "id": "interaction-1",
        "type": 2,
        "channel_id": "channel-1",
        "guild_id": "guild-1",
        "application_id": "app-123",
        "token": "interaction-token",
        "member": {
            "user": {
                "id": "user-1",
                "username": "tester",
            }
        },
        "data": {
            "name": "analyze",
            "options": [
                {"name": "stock_code", "value": "600519"},
            ],
        },
    }
    body = json.dumps(payload).encode("utf-8")

    message, response = platform.handle_webhook(
        _sign_headers(signing_key, body),
        body,
        payload,
    )

    # 应返回 type 5 延迟 ACK
    assert response is not None
    assert response.status_code == 200
    assert response.body == {"type": 5}

    # 同时仍解析出消息
    assert message is not None
    assert message.platform == "discord"
    assert message.chat_id == "channel-1"
    assert message.chat_type == ChatType.GROUP
    assert message.user_id == "user-1"
    assert message.user_name == "tester"
    assert message.content == "/analyze 600519"
    # follow-up 需要的字段存在于 raw_data
    assert message.raw_data.get("application_id") == "app-123"
    assert message.raw_data.get("token") == "interaction-token"


def test_invalid_signature_ping_request_is_rejected_before_challenge():
    signing_key = SigningKey.generate()
    platform = _make_platform(signing_key.verify_key.encode().hex())
    payload = {"type": 1}
    body = json.dumps(payload).encode("utf-8")
    headers = _sign_headers(signing_key, body)
    headers["X-Signature-Ed25519"] = "00" * 64

    message, response = platform.handle_webhook(headers, body, payload)

    assert message is None
    assert response is not None
    assert response.status_code == 401
    assert response.body == {"error": "Invalid Discord signature"}


def test_missing_signature_header_is_rejected():
    signing_key = SigningKey.generate()
    platform = _make_platform(signing_key.verify_key.encode().hex())
    payload = {
        "id": "interaction-2",
        "type": 2,
        "data": {"name": "help"},
    }
    body = json.dumps(payload).encode("utf-8")

    message, response = platform.handle_webhook(
        {"X-Signature-Timestamp": _current_timestamp()},
        body,
        payload,
    )

    assert message is None
    assert response is not None
    assert response.status_code == 401
    assert response.body == {"error": "Invalid Discord signature"}


def test_invalid_public_key_configuration_is_rejected():
    platform = _make_platform("not-a-hex-public-key")
    payload = {"type": 1}
    body = json.dumps(payload).encode("utf-8")

    message, response = platform.handle_webhook(
        {
            "X-Signature-Ed25519": "00" * 64,
            "X-Signature-Timestamp": _current_timestamp(),
        },
        body,
        payload,
    )

    assert message is None
    assert response is not None
    assert response.status_code == 401
    assert response.body == {"error": "Invalid Discord signature"}


def test_expired_timestamp_is_rejected():
    """过期 timestamp（超出 ±5 分钟窗口）应被拒绝，防重放攻击。"""
    signing_key = SigningKey.generate()
    platform = _make_platform(signing_key.verify_key.encode().hex())
    payload = {"type": 1}
    body = json.dumps(payload).encode("utf-8")
    # 10 分钟前的 timestamp
    stale_ts = str(int(time.time()) - 600)

    message, response = platform.handle_webhook(
        _sign_headers(signing_key, body, timestamp=stale_ts),
        body,
        payload,
    )

    assert message is None
    assert response is not None
    assert response.status_code == 401


def test_format_response_wraps_interaction_callback():
    """type=2 交互响应应使用 Interaction Response 回调格式（type=4 + data）。"""
    from bot.models import BotMessage, BotResponse, ChatType

    platform = _make_platform("00" * 32)
    message = BotMessage(
        platform="discord",
        message_id="msg-1",
        user_id="user-1",
        user_name="tester",
        chat_id="channel-1",
        chat_type=ChatType.GROUP,
        content="/analyze 600519",
        raw_data={"type": 2, "data": {"name": "analyze"}},
    )
    response = BotResponse.text_response("分析结果")

    webhook_response = platform.format_response(response, message)

    assert webhook_response.status_code == 200
    assert webhook_response.body["type"] == 4
    assert "data" in webhook_response.body
    assert webhook_response.body["data"]["content"] == "分析结果"
    assert webhook_response.body["data"]["tts"] is False


def test_send_followup_patches_original_message():
    """send_followup 应 PATCH Discord follow-up webhook。"""
    from bot.models import BotMessage, BotResponse, ChatType

    platform = _make_platform("00" * 32)
    message = BotMessage(
        platform="discord",
        message_id="msg-1",
        user_id="user-1",
        user_name="tester",
        chat_id="channel-1",
        chat_type=ChatType.GROUP,
        content="/analyze 600519",
        raw_data={
            "type": 2,
            "application_id": "app-123",
            "token": "interaction-token",
        },
    )
    response = BotResponse.text_response("分析结果")

    with patch("bot.platforms.discord.requests") as mock_requests:
        mock_resp = type("R", (), {"status_code": 200, "text": "ok"})()
        mock_requests.patch.return_value = mock_resp
        result = platform.send_followup(response, message)

    assert result is True
    mock_requests.patch.assert_called_once()
    call_args = mock_requests.patch.call_args
    assert "/app-123/interaction-token/messages/@original" in call_args[0][0]
    assert call_args[1]["json"]["content"] == "分析结果"


def test_send_followup_chunks_long_content():
    """超过 2000 字符的 follow-up 应被分块：首块 PATCH，后续 POST。"""
    from bot.models import BotMessage, BotResponse, ChatType

    platform = _make_platform("00" * 32)
    message = BotMessage(
        platform="discord",
        message_id="msg-1",
        user_id="user-1",
        user_name="tester",
        chat_id="channel-1",
        chat_type=ChatType.GROUP,
        content="/analyze 600519",
        raw_data={
            "type": 2,
            "application_id": "app-123",
            "token": "interaction-token",
        },
    )
    # 生成超过 2000 字符的内容
    long_content = "A" * 3500
    response = BotResponse.text_response(long_content)

    with patch("bot.platforms.discord.requests") as mock_requests:
        mock_resp = type("R", (), {"status_code": 200, "text": "ok"})()
        mock_requests.patch.return_value = mock_resp
        mock_requests.post.return_value = mock_resp
        result = platform.send_followup(response, message)

    assert result is True
    # 首块使用 PATCH
    mock_requests.patch.assert_called_once()
    patch_url = mock_requests.patch.call_args[0][0]
    assert "/messages/@original" in patch_url
    # 后续块使用 POST
    assert mock_requests.post.call_count >= 1
    post_url = mock_requests.post.call_args[0][0]
    assert post_url.endswith("/app-123/interaction-token")


def test_send_followup_missing_token_returns_false():
    """缺少 interaction token 时 send_followup 应返回 False。"""
    from bot.models import BotMessage, BotResponse, ChatType

    platform = _make_platform("00" * 32)
    message = BotMessage(
        platform="discord",
        message_id="msg-1",
        user_id="user-1",
        user_name="tester",
        chat_id="channel-1",
        chat_type=ChatType.GROUP,
        content="/analyze 600519",
        raw_data={"type": 2},
    )
    response = BotResponse.text_response("分析结果")
    assert platform.send_followup(response, message) is False


def test_non_numeric_timestamp_is_rejected():
    """非数字 timestamp 应被拒绝。"""
    signing_key = SigningKey.generate()
    platform = _make_platform(signing_key.verify_key.encode().hex())
    payload = {"type": 1}
    body = json.dumps(payload).encode("utf-8")

    message, response = platform.handle_webhook(
        _sign_headers(signing_key, body, timestamp="not-a-number"),
        body,
        payload,
    )

    assert message is None
    assert response is not None
    assert response.status_code == 401


def test_boolean_option_true_emits_name():
    """布尔 True 选项应输出 option name，而非字面 'true'。"""
    platform = _make_platform("00" * 32)
    interaction_data = {
        "name": "analyze",
        "options": [
            {"name": "stock_code", "value": "600519"},
            {"name": "full", "value": True},
        ],
    }
    content = platform._build_command_content(interaction_data)
    assert content == "/analyze 600519 full"


def test_boolean_option_false_is_omitted():
    """布尔 False 选项应被忽略，不出现在命令内容中。"""
    platform = _make_platform("00" * 32)
    interaction_data = {
        "name": "analyze",
        "options": [
            {"name": "stock_code", "value": "600519"},
            {"name": "full", "value": False},
        ],
    }
    content = platform._build_command_content(interaction_data)
    assert content == "/analyze 600519"
