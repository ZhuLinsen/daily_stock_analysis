"""Public Discord Interaction webhook endpoint and response-lifecycle hook."""

import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from bot.handler import get_platform, handle_webhook_async
from bot.models import WebhookResponse


router = APIRouter(tags=["bot"])
logger = logging.getLogger(__name__)

DEFERRED_CALLBACKS_SCOPE_KEY = "dsa.discord.deferred_callbacks"


class DiscordDeferredCallbackMiddleware:
    """Run Discord callbacks after the outermost final response body send."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http" or scope.get("path") != "/bot/discord":
            await self.app(scope, receive, send)
            return

        callbacks = []
        scope[DEFERRED_CALLBACKS_SCOPE_KEY] = callbacks
        final_body_sent = False

        async def send_then_dispatch(message):
            nonlocal final_body_sent
            await send(message)
            if (
                message.get("type") == "http.response.body"
                and not message.get("more_body", False)
                and not final_body_sent
            ):
                final_body_sent = True
                for callback in tuple(callbacks):
                    try:
                        await callback()
                    except Exception:
                        logger.exception(
                            "[Discord] deferred callback failed after ACK flush"
                        )

        await self.app(scope, receive, send_then_dispatch)


@router.post("/bot/discord", include_in_schema=False)
async def discord_interaction(request: Request) -> JSONResponse:
    """Verify and acknowledge a Discord Interaction request."""
    body = await request.body()
    headers = dict(request.headers)
    deferred_callbacks = request.scope.get(DEFERRED_CALLBACKS_SCOPE_KEY)

    # Signature verification belongs in front of all runtime feature flags.
    # Otherwise BOT_ENABLED=false could turn this public endpoint into an
    # unsigned 200 response. Discord PING is also answered while the command
    # dispatcher is disabled so Developer Portal endpoint validation remains
    # deterministic.
    platform = get_platform("discord")
    if platform is None or not platform.verify_request(headers, body):
        response = WebhookResponse.error("Invalid Discord signature", 401)
    else:
        try:
            payload = await request.json()
        except ValueError:
            payload = None
        if isinstance(payload, dict) and payload.get("type") == 1:
            response = WebhookResponse.success({"type": 1})
        else:
            response = await handle_webhook_async(
                "discord",
                headers,
                body,
                dict(request.query_params.multi_items()),
                deferred_callbacks=deferred_callbacks,
            )
    return JSONResponse(
        status_code=response.status_code,
        content=response.body,
        headers=response.headers,
    )
