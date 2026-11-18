"""Shared synchronous Responses transport for ChatGPT plan usage."""
from dataclasses import dataclass
from typing import Optional

import httpx
import openai

from src.config import get_config
from src.llm.model_source import CHATGPT_SIWC
from src.llm.provider_cache import filter_prompt_cache_telemetry
from src.llm.usage import normalize_litellm_usage
from src.services.chatgpt_oauth_service import ChatGPTError, RESOURCE


@dataclass
class ChatGPTResponse:
    items: list
    model: str
    usage: dict
    response_id: Optional[str] = None

    def final_text(self):
        messages = [
            item for item in self.items if item.get("type") == "message" and item.get("role") == "assistant"
        ]
        final = [item for item in messages if item.get("phase") == "final_answer"]
        if not final and any(item.get("phase") is not None for item in messages):
            raise self.output_error("ChatGPT did not return a final answer")
        content = [part for item in (final or messages) for part in item.get("content", [])]
        if any(part.get("type") == "refusal" for part in content):
            raise self.output_error("ChatGPT refused the request")
        text = "\n".join(part["text"] for part in content if part.get("type") == "output_text")
        if not text.strip():
            raise self.output_error("ChatGPT returned no final text")
        return text

    def output_error(self, message):
        return ChatGPTError("chatgpt_invalid_output", message, request_id=self.response_id)


def _dump(item):
    return item.model_dump(mode="json", by_alias=True, exclude_unset=True)


def consume_responses(stream, progress=None, request_id=None):
    done_items = {}
    completed = None
    characters = 0
    for event in stream:
        if event.type == "response.output_item.done":
            if event.output_index < 0 or event.output_index in done_items:
                raise ChatGPTError("chatgpt_protocol_error", "Invalid output item index", request_id=request_id)
            done_items[event.output_index] = _dump(event.item)
        elif event.type == "response.completed":
            if completed is not None:
                raise ChatGPTError("chatgpt_protocol_error", "Repeated completion event", request_id=request_id)
            completed = event.response
        elif event.type in {"response.failed", "response.incomplete", "error"}:
            response = getattr(event, "response", None)
            detail = getattr(response, "error", None) or getattr(response, "incomplete_details", None) or event
            raise ChatGPTError.upstream(
                "chatgpt_inference_failed", "ChatGPT did not complete the response",
                _dump(detail), request_id=request_id or getattr(response, "id", None),
            )
        elif progress and event.type == "response.output_text.delta":
            characters += len(event.delta)
            progress(characters)

    if completed is None or completed.status != "completed":
        raise ChatGPTError("chatgpt_stream_incomplete", "ChatGPT stream ended without completion", request_id=request_id)

    items = [_dump(item) for item in completed.output] if completed.output else [
        done_items[index] for index in sorted(done_items)
    ]
    usage = normalize_litellm_usage(completed.usage, model=completed.model, provider=CHATGPT_SIWC)
    usage["provider"] = CHATGPT_SIWC
    return ChatGPTResponse(items, completed.model, usage, completed.id)


def request_responses(service, source, *, items, instructions, timeout, tools=None, progress=None):
    payload = {
        "model": source.model, "input": items, "instructions": instructions, "store": False, "stream": True,
    }
    if tools:
        payload.update(tools=tools, tool_choice="auto")

    client = None
    request_id = None

    def dispatch(bearer):
        nonlocal client
        client = openai.OpenAI(
            api_key=bearer, base_url=RESOURCE, max_retries=0,
            http_client=httpx.Client(trust_env=False, follow_redirects=False, timeout=timeout),
        )
        # The SDK otherwise looks up organization and project in the legacy environment.
        client.organization = None
        client.project = None
        return client.responses.create(**payload, timeout=timeout)

    try:
        with service.start_request(source, dispatch) as stream:
            request_id = stream.response.headers.get("x-request-id")
            result = consume_responses(stream, progress, request_id)
        service.ensure_active(source)
        result.usage = filter_prompt_cache_telemetry(result.usage, get_config())
        return result
    except openai.APIStatusError as exc:
        raise ChatGPTError.upstream(
            "chatgpt_http_error", "OpenAI rejected the request", exc.body,
            status=exc.status_code, request_id=exc.request_id,
        ) from None
    except (openai.APITimeoutError, httpx.TimeoutException):
        raise ChatGPTError("chatgpt_timeout", "ChatGPT request timed out", request_id=request_id) from None
    except openai.APIError as exc:
        raise ChatGPTError.upstream(
            "chatgpt_inference_failed", "ChatGPT request failed", exc.body, request_id=request_id,
        ) from None
    except (httpx.HTTPError, ValueError):
        raise ChatGPTError("chatgpt_stream_error", "Could not read the ChatGPT response", request_id=request_id) from None
    finally:
        if client is not None:
            client.close()
