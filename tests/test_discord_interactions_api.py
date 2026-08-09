# -*- coding: utf-8 -*-
import asyncio
import json
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient
from nacl.signing import SigningKey

from api.app import create_app
from bot import handler as bot_handler
from bot.models import BotMessage, BotResponse, ChatType, WebhookResponse
from bot.platforms.discord import DiscordPlatform


def _signed_request(signing_key: SigningKey, payload: dict) -> tuple[bytes, dict]:
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    timestamp = str(int(time.time()))
    signature = signing_key.sign(timestamp.encode("utf-8") + body).signature.hex()
    return body, {
        "X-Signature-Ed25519": signature,
        "X-Signature-Timestamp": timestamp,
        "Content-Type": "application/json",
    }


def _client_with_discord_key(tmp_path: Path, signing_key: SigningKey) -> TestClient:
    platform = DiscordPlatform.__new__(DiscordPlatform)
    platform._interactions_public_key = signing_key.verify_key.encode().hex()
    platform.send_followup = lambda response, message: True
    bot_handler._platform_instances["discord"] = platform
    return TestClient(create_app(static_dir=tmp_path / "empty-static"))


def test_post_discord_accepts_signed_ping_and_returns_pong(tmp_path):
    signing_key = SigningKey.generate()
    body, headers = _signed_request(signing_key, {"type": 1})
    client = _client_with_discord_key(tmp_path, signing_key)

    with patch(
        "src.config.get_config", return_value=SimpleNamespace(bot_enabled=True)
    ):
        response = client.post("/bot/discord", content=body, headers=headers)

    assert response.status_code == 200
    assert response.json() == {"type": 1}


def test_post_discord_rejects_missing_or_invalid_signatures(tmp_path):
    signing_key = SigningKey.generate()
    body, headers = _signed_request(signing_key, {"type": 1})
    client = _client_with_discord_key(tmp_path, signing_key)

    missing = client.post(
        "/bot/discord",
        content=body,
        headers={"Content-Type": "application/json"},
    )
    invalid_headers = dict(headers)
    invalid_headers["X-Signature-Ed25519"] = "00" * 64
    invalid = client.post("/bot/discord", content=body, headers=invalid_headers)

    assert missing.status_code == 401
    assert invalid.status_code == 401


def test_post_discord_returns_deferred_ack_for_signed_application_command(tmp_path):
    signing_key = SigningKey.generate()
    payload = {
        "id": "interaction-1",
        "application_id": "application-1",
        "token": "interaction-token",
        "type": 2,
        "channel_id": "channel-1",
        "member": {"user": {"id": "user-1", "username": "tester"}},
        "data": {"name": "help"},
    }
    body, headers = _signed_request(signing_key, payload)
    client = _client_with_discord_key(tmp_path, signing_key)

    with patch(
        "src.config.get_config", return_value=SimpleNamespace(bot_enabled=True)
    ):
        response = client.post("/bot/discord", content=body, headers=headers)

    assert response.status_code == 200
    assert response.json() == {"type": 5}


def test_signed_application_command_still_gets_deferred_ack_when_bot_disabled(
    tmp_path,
):
    signing_key = SigningKey.generate()
    payload = {
        "id": "interaction-disabled",
        "application_id": "application-1",
        "token": "interaction-token",
        "type": 2,
        "channel_id": "channel-1",
        "member": {"user": {"id": "user-1", "username": "tester"}},
        "data": {"name": "help"},
    }
    body, headers = _signed_request(signing_key, payload)
    client = _client_with_discord_key(tmp_path, signing_key)

    with patch(
        "src.config.get_config", return_value=SimpleNamespace(bot_enabled=False)
    ), patch("bot.handler.get_dispatcher") as get_dispatcher:
        response = client.post("/bot/discord", content=body, headers=headers)

    assert response.status_code == 200
    assert response.json() == {"type": 5}
    get_dispatcher.assert_not_called()


def test_discord_route_bypasses_admin_cookie_without_weakening_api_auth(tmp_path):
    signing_key = SigningKey.generate()
    body, headers = _signed_request(signing_key, {"type": 1})
    client = _client_with_discord_key(tmp_path, signing_key)

    with patch("api.middlewares.auth.is_auth_enabled", return_value=True):
        discord_response = client.post("/bot/discord", content=body, headers=headers)
        api_response = client.get("/api/v1/stocks")

    assert discord_response.status_code == 200
    assert discord_response.json() == {"type": 1}
    assert api_response.status_code == 401


def test_deferred_followup_starts_only_after_outer_ack_body_is_flushed(tmp_path):
    async def scenario():
        events = []
        payload = {
            "id": "interaction-race",
            "application_id": "application-1",
            "token": "interaction-token",
            "type": 2,
            "channel_id": "channel-1",
            "member": {"user": {"id": "user-1", "username": "tester"}},
            "data": {"name": "help"},
        }
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        message = BotMessage(
            platform="discord",
            message_id="interaction-race",
            user_id="user-1",
            user_name="tester",
            chat_id="channel-1",
            chat_type=ChatType.GROUP,
            content="/help",
            raw_data=dict(payload),
        )

        platform = MagicMock()
        platform.verify_request.return_value = True
        platform.handle_webhook.return_value = (
            message,
            WebhookResponse.success({"type": 5}),
        )
        platform.send_followup.side_effect = lambda response, original: events.append(
            "followup"
        ) or True
        dispatcher = MagicMock()

        async def dispatch_after_flush(original):
            events.append("dispatcher")
            return BotResponse.text_response("help response")

        dispatcher.dispatch_async = AsyncMock(side_effect=dispatch_after_flush)

        # Exercise the real application stack, including AuthMiddleware's
        # BaseHTTPMiddleware streaming wrapper.
        app = create_app(static_dir=tmp_path / "empty-static")
        receive_called = False
        disconnect = asyncio.Event()

        async def receive():
            nonlocal receive_called
            if receive_called:
                await disconnect.wait()
                return {"type": "http.disconnect"}
            receive_called = True
            return {"type": "http.request", "body": body, "more_body": False}

        async def send(event):
            events.append(event["type"])
            if event["type"] == "http.response.body" and not event.get(
                "more_body", False
            ):
                events.append("final_body_send_started")
                # A call_soon barrier gives already-runnable inner background
                # work a deterministic loop turn without relying on sleeps.
                loop_turn = asyncio.Event()
                asyncio.get_running_loop().call_soon(loop_turn.set)
                await loop_turn.wait()
                assert dispatcher.dispatch_async.await_count == 0
                assert "followup" not in events
                events.append("final_body_send_completed")

        scope = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "POST",
            "scheme": "https",
            "path": "/bot/discord",
            "raw_path": b"/bot/discord",
            "query_string": b"",
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode("ascii")),
            ],
            "client": ("127.0.0.1", 12345),
            "server": ("testserver", 443),
            "root_path": "",
        }

        with patch("api.discord.get_platform", return_value=platform), patch(
            "bot.handler.get_platform", return_value=platform
        ), patch("bot.handler.get_dispatcher", return_value=dispatcher), patch(
            "src.config.get_config", return_value=SimpleNamespace(bot_enabled=True)
        ), patch(
            "api.middlewares.auth.is_auth_enabled", return_value=True
        ):
            await app(scope, receive, send)

        assert events.index("final_body_send_completed") < events.index("dispatcher")
        assert events.index("dispatcher") < events.index("followup")
        dispatcher.dispatch_async.assert_awaited_once_with(message)
        platform.send_followup.assert_called_once()

    asyncio.run(scenario())
