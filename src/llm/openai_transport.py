# -*- coding: utf-8 -*-
"""
===================================
Native HTTPX OpenAI Dual-Protocol Transport (Chat Completions + Responses API)
===================================

Issue #2622 Phase 2a/2b: lightweight ``httpx[socks]`` implementation replacing
``litellm`` for OpenAI Chat Completions and OpenAI Responses providers while
preserving LiteLLM response/exception/Router contracts.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Callable, Dict, Iterable, Iterator, List, Mapping, Optional
import uuid

import httpx

from src.core.stock_execution_context import raise_if_stock_cancelled
from src.llm.native_types import (
    DEFAULT_PROVIDER_BASES,
    FALLBACK_ONLY_PROVIDERS,
    NATIVE_OPENAI_PROVIDERS,
    NativeAPIError,
    NativeAuthenticationError,
    NativeBadRequestError,
    NativeChoice,
    NativeCompletionResponse,
    NativeContextWindowExceededError,
    NativeFunctionCall,
    NativeMessage,
    NativeRateLimitError,
    NativeStreamChunk,
    NativeToolCall,
    NativeUsage,
    PreparedRequest,
    execute_pooled_completion,
    extract_client_overrides,
    has_header_case_insensitive,
    merge_header_overrides,
    resolve_native_protocol,
    resolve_openai_wire_protocol,
    stream_pooled_completion,
    strip_provider_prefix,
)
from src.llm.pool import DeploymentEntry, DeploymentPool
from src.llm.sse import iter_sse_json_events

logger = logging.getLogger(__name__)

_CHAT_COMPLETIONS_OPTIONAL_KEYS = (
    "temperature",
    "top_p",
    "max_tokens",
    "max_completion_tokens",
    "stop",
    "seed",
    "presence_penalty",
    "frequency_penalty",
    "response_format",
    "tools",
    "tool_choice",
    "parallel_tool_calls",
    "reasoning_effort",
    "user",
)

_FILTERED_REQUEST_KWARGS = frozenset(
    {
        "model",
        "messages",
        "stream",
        "api_key",
        "api_base",
        "base_url",
        "extra_headers",
        "headers",
        "default_headers",
        "custom_llm_provider",
        "wire_protocol",
        "timeout",
        "num_retries",
        "fallbacks",
        "metadata",
        "caching",
        "drop_params",
        "client",
    }
)


def supports_native_openai_provider(
    model: str,
    *,
    api_base: Optional[str] = None,
    custom_llm_provider: Optional[str] = None,
) -> bool:
    """Return True if model/provider speaks native OpenAI Chat or Responses protocol."""
    protocol = resolve_native_protocol(
        model,
        api_base=api_base,
        custom_llm_provider=custom_llm_provider,
    )
    if protocol in {"openai_chat", "openai_responses"}:
        return True
    provider_hint = (custom_llm_provider or "").strip().lower()
    if provider_hint in {"openai", "openai_compatible"}:
        return True
    provider, _ = strip_provider_prefix(model)
    return bool(api_base and provider not in FALLBACK_ONLY_PROVIDERS and protocol is None)


def resolve_openai_endpoint_url(api_base: str, protocol: str) -> str:
    """Resolve OpenAI Chat Completions or Responses API endpoint URL without doubling paths."""
    base = (api_base or DEFAULT_PROVIDER_BASES["openai"]).strip().rstrip("/")
    suffix = "/responses" if protocol == "openai_responses" else "/chat/completions"
    if base.endswith(suffix):
        return base
    if protocol == "openai_responses" and base.endswith("/chat/completions"):
        return base[: -len("/chat/completions")] + "/responses"
    if protocol == "openai_chat" and base.endswith("/responses"):
        return base[: -len("/responses")] + "/chat/completions"
    return base + suffix


def _normalize_usage(raw_usage: Any) -> Optional[NativeUsage]:
    if not isinstance(raw_usage, Mapping):
        return None
    prompt_tokens = raw_usage.get("prompt_tokens")
    if prompt_tokens is None:
        prompt_tokens = raw_usage.get("input_tokens")
    completion_tokens = raw_usage.get("completion_tokens")
    if completion_tokens is None:
        completion_tokens = raw_usage.get("output_tokens")
    total_tokens = raw_usage.get("total_tokens")
    if total_tokens is None and prompt_tokens is not None and completion_tokens is not None:
        try:
            total_tokens = int(prompt_tokens) + int(completion_tokens)
        except (TypeError, ValueError):
            total_tokens = None

    prompt_details: Optional[Dict[str, Any]] = None
    for detail_key in ("prompt_tokens_details", "input_tokens_details"):
        raw_detail = raw_usage.get(detail_key)
        if isinstance(raw_detail, Mapping):
            prompt_details = dict(raw_detail)
            break
    if prompt_details is None and raw_usage.get("prompt_cache_hit_tokens") is not None:
        prompt_details = {"cached_tokens": raw_usage.get("prompt_cache_hit_tokens")}

    completion_details: Optional[Dict[str, Any]] = None
    for detail_key in ("completion_tokens_details", "output_tokens_details"):
        raw_detail = raw_usage.get(detail_key)
        if isinstance(raw_detail, Mapping):
            completion_details = dict(raw_detail)
            break

    extra: Dict[str, Any] = {}
    for key in (
        "prompt_cache_hit_tokens",
        "prompt_cache_miss_tokens",
        "cached_tokens",
        "cache_read_tokens",
        "cache_write_tokens",
    ):
        if raw_usage.get(key) is not None:
            extra[key] = raw_usage.get(key)

    return NativeUsage(
        prompt_tokens=int(prompt_tokens) if prompt_tokens is not None else None,
        completion_tokens=int(completion_tokens) if completion_tokens is not None else None,
        total_tokens=int(total_tokens) if total_tokens is not None else None,
        prompt_tokens_details=prompt_details,
        completion_tokens_details=completion_details,
        extra=extra,
    )


# ============================================================
# Chat Completions Request / Response Translation
# ============================================================


def build_chat_completions_payload(
    *,
    wire_model: str,
    messages: List[Dict[str, Any]],
    stream: bool = False,
    deployment_extra_body: Optional[Mapping[str, Any]] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Assemble an OpenAI Chat Completions JSON request body."""
    body: Dict[str, Any] = {
        "model": wire_model,
        "messages": messages,
        "stream": bool(stream),
    }
    if stream:
        stream_options = kwargs.get("stream_options")
        if isinstance(stream_options, Mapping):
            body["stream_options"] = dict(stream_options)
        else:
            body["stream_options"] = {"include_usage": True}

    for key in _CHAT_COMPLETIONS_OPTIONAL_KEYS:
        if key in kwargs and kwargs[key] is not None:
            body[key] = kwargs[key]

    merged_extra: Dict[str, Any] = {}
    if isinstance(deployment_extra_body, Mapping):
        merged_extra.update(deployment_extra_body)
    if isinstance(kwargs.get("extra_body"), Mapping):
        merged_extra.update(kwargs["extra_body"])
    for key, value in merged_extra.items():
        if value is not None:
            body[key] = value

    return body


def parse_chat_completion_response(
    payload: Mapping[str, Any],
    *,
    default_model: str = "",
) -> NativeCompletionResponse:
    """Normalize a Chat Completions JSON payload into :class:`NativeCompletionResponse`."""
    raw_choices = payload.get("choices") or []
    choices: List[NativeChoice] = []
    for idx, raw_choice in enumerate(raw_choices):
        if not isinstance(raw_choice, Mapping):
            continue
        msg_raw = raw_choice.get("message") or {}
        tool_calls: Optional[List[NativeToolCall]] = None
        raw_tcs = msg_raw.get("tool_calls") if isinstance(msg_raw, Mapping) else None
        if isinstance(raw_tcs, list) and raw_tcs:
            tool_calls = []
            for tc_idx, raw_tc in enumerate(raw_tcs):
                if not isinstance(raw_tc, Mapping):
                    continue
                fn = raw_tc.get("function") or {}
                tool_calls.append(
                    NativeToolCall(
                        id=str(raw_tc.get("id") or f"call_{tc_idx}"),
                        type=str(raw_tc.get("type") or "function"),
                        index=int(raw_tc.get("index", tc_idx)),
                        function=NativeFunctionCall(
                            name=fn.get("name") if isinstance(fn, Mapping) else None,
                            arguments=fn.get("arguments") if isinstance(fn, Mapping) else None,
                        ),
                    )
                )

        reasoning = (
            msg_raw.get("reasoning_content") or msg_raw.get("reasoning")
            if isinstance(msg_raw, Mapping)
            else None
        )
        msg = NativeMessage(
            role=str(msg_raw.get("role") or "assistant") if isinstance(msg_raw, Mapping) else "assistant",
            content=msg_raw.get("content") if isinstance(msg_raw, Mapping) else None,
            tool_calls=tool_calls,
            reasoning_content=reasoning,
        )
        choices.append(
            NativeChoice(
                index=int(raw_choice.get("index", idx)),
                message=msg,
                finish_reason=raw_choice.get("finish_reason"),
            )
        )

    return NativeCompletionResponse(
        id=str(payload.get("id") or f"chatcmpl-{uuid.uuid4().hex[:12]}"),
        model=str(payload.get("model") or default_model),
        choices=choices,
        usage=_normalize_usage(payload.get("usage")),
        created=int(payload.get("created") or time.time()),
        object=str(payload.get("object") or "chat.completion"),
    )


def parse_chat_completion_stream_chunk(
    payload: Mapping[str, Any],
    *,
    default_model: str = "",
) -> Optional[NativeStreamChunk]:
    """Normalize a single Chat Completions SSE JSON chunk into :class:`NativeStreamChunk`."""
    raw_choices = payload.get("choices") or []
    usage = _normalize_usage(payload.get("usage"))
    choices: List[NativeChoice] = []
    for idx, raw_choice in enumerate(raw_choices):
        if not isinstance(raw_choice, Mapping):
            continue
        raw_delta = raw_choice.get("delta") or {}
        tool_calls: Optional[List[NativeToolCall]] = None
        raw_tcs = raw_delta.get("tool_calls") if isinstance(raw_delta, Mapping) else None
        if isinstance(raw_tcs, list) and raw_tcs:
            tool_calls = []
            for tc_idx, raw_tc in enumerate(raw_tcs):
                if not isinstance(raw_tc, Mapping):
                    continue
                fn = raw_tc.get("function") or {}
                tool_calls.append(
                    NativeToolCall(
                        id=raw_tc.get("id"),
                        type=str(raw_tc.get("type") or "function"),
                        index=int(raw_tc.get("index", tc_idx)),
                        function=NativeFunctionCall(
                            name=fn.get("name") if isinstance(fn, Mapping) else None,
                            arguments=fn.get("arguments") if isinstance(fn, Mapping) else None,
                        ),
                    )
                )
        reasoning = (
            raw_delta.get("reasoning_content") or raw_delta.get("reasoning")
            if isinstance(raw_delta, Mapping)
            else None
        )
        delta = NativeMessage(
            role=str(raw_delta.get("role") or "assistant") if isinstance(raw_delta, Mapping) else "assistant",
            content=raw_delta.get("content") if isinstance(raw_delta, Mapping) else None,
            tool_calls=tool_calls,
            reasoning_content=reasoning,
        )
        choices.append(
            NativeChoice(
                index=int(raw_choice.get("index", idx)),
                delta=delta,
                finish_reason=raw_choice.get("finish_reason"),
            )
        )

    if not choices and usage is None:
        return None
    if not choices and usage is not None:
        choices = [NativeChoice(index=0, delta=NativeMessage(), finish_reason=None)]

    return NativeStreamChunk(
        id=str(payload.get("id") or f"chatcmpl-{uuid.uuid4().hex[:12]}"),
        model=str(payload.get("model") or default_model),
        choices=choices,
        usage=usage,
        created=int(payload.get("created") or time.time()),
    )


# ============================================================
# Responses API Request / Response Translation
# ============================================================


def _convert_content_parts_for_responses(content: Any, *, role: str) -> Any:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return str(content or "")

    converted: List[Dict[str, Any]] = []
    text_type = "output_text" if role == "assistant" else "input_text"
    for part in content:
        if isinstance(part, str):
            converted.append({"type": text_type, "text": part})
            continue
        if not isinstance(part, Mapping):
            continue
        ptype = str(part.get("type") or "text")
        if ptype in {"text", "input_text", "output_text"}:
            converted.append({"type": text_type, "text": str(part.get("text") or "")})
        elif ptype == "image_url":
            img = part.get("image_url")
            url = img.get("url") if isinstance(img, Mapping) else img
            if url:
                converted.append({"type": "input_image", "image_url": str(url)})
        else:
            converted.append(dict(part))
    return converted


def _convert_tools_for_responses(tools: Any) -> Optional[List[Dict[str, Any]]]:
    if not isinstance(tools, list) or not tools:
        return None
    converted: List[Dict[str, Any]] = []
    for tool in tools:
        if not isinstance(tool, Mapping):
            continue
        if tool.get("type") == "function" and isinstance(tool.get("function"), Mapping):
            fn = tool["function"]
            entry: Dict[str, Any] = {
                "type": "function",
                "name": fn.get("name"),
            }
            if fn.get("description") is not None:
                entry["description"] = fn.get("description")
            if fn.get("parameters") is not None:
                entry["parameters"] = fn.get("parameters")
            if fn.get("strict") is not None:
                entry["strict"] = fn.get("strict")
            converted.append(entry)
        else:
            converted.append(dict(tool))
    return converted or None


def build_responses_api_payload(
    *,
    wire_model: str,
    messages: List[Dict[str, Any]],
    stream: bool = False,
    deployment_extra_body: Optional[Mapping[str, Any]] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Translate Chat Completions-style inputs into an OpenAI Responses API JSON body."""
    instructions_parts: List[str] = []
    input_items: List[Dict[str, Any]] = []

    for msg in messages:
        if not isinstance(msg, Mapping):
            continue
        role = str(msg.get("role") or "user").strip().lower()
        if role in {"system", "developer"}:
            raw_content = msg.get("content")
            if isinstance(raw_content, str) and raw_content.strip():
                instructions_parts.append(raw_content.strip())
            elif isinstance(raw_content, list):
                text = " ".join(
                    str(p.get("text") or "")
                    for p in raw_content
                    if isinstance(p, Mapping) and p.get("text")
                ).strip()
                if text:
                    instructions_parts.append(text)
            continue

        if role == "tool":
            raw_out = msg.get("content")
            output_text = raw_out if isinstance(raw_out, str) else json.dumps(raw_out, ensure_ascii=False)
            input_items.append(
                {
                    "type": "function_call_output",
                    "call_id": str(msg.get("tool_call_id") or ""),
                    "output": output_text,
                }
            )
            continue

        if role == "assistant":
            raw_content = msg.get("content")
            if raw_content:
                input_items.append(
                    {
                        "role": "assistant",
                        "content": _convert_content_parts_for_responses(raw_content, role="assistant"),
                    }
                )
            for tc in msg.get("tool_calls") or []:
                if not isinstance(tc, Mapping):
                    continue
                fn = tc.get("function") or {}
                args = fn.get("arguments") if isinstance(fn, Mapping) else ""
                if not isinstance(args, str):
                    args = json.dumps(args or {}, ensure_ascii=False)
                input_items.append(
                    {
                        "type": "function_call",
                        "call_id": str(tc.get("id") or f"call_{uuid.uuid4().hex[:8]}"),
                        "name": str(fn.get("name") or "") if isinstance(fn, Mapping) else "",
                        "arguments": args,
                    }
                )
            continue

        input_items.append(
            {
                "role": "user",
                "content": _convert_content_parts_for_responses(msg.get("content", ""), role="user"),
            }
        )

    body: Dict[str, Any] = {
        "model": wire_model,
        "input": input_items,
        "stream": bool(stream),
    }
    if instructions_parts:
        body["instructions"] = "\n\n".join(instructions_parts)

    responses_tools = _convert_tools_for_responses(kwargs.get("tools"))
    if responses_tools:
        body["tools"] = responses_tools
    if kwargs.get("tool_choice") is not None:
        body["tool_choice"] = kwargs["tool_choice"]
    if kwargs.get("temperature") is not None:
        body["temperature"] = kwargs["temperature"]
    if kwargs.get("top_p") is not None:
        body["top_p"] = kwargs["top_p"]

    max_out = kwargs.get("max_output_tokens")
    if max_out is None:
        max_out = kwargs.get("max_completion_tokens")
    if max_out is None:
        max_out = kwargs.get("max_tokens")
    if max_out is not None:
        body["max_output_tokens"] = max_out

    if kwargs.get("reasoning_effort") is not None:
        body["reasoning"] = {"effort": kwargs["reasoning_effort"]}

    merged_extra: Dict[str, Any] = {}
    if isinstance(deployment_extra_body, Mapping):
        merged_extra.update(deployment_extra_body)
    if isinstance(kwargs.get("extra_body"), Mapping):
        merged_extra.update(kwargs["extra_body"])
    for key, value in merged_extra.items():
        if value is not None:
            body[key] = value

    return body


def parse_responses_api_response(
    payload: Mapping[str, Any],
    *,
    default_model: str = "",
) -> NativeCompletionResponse:
    """Normalize an OpenAI Responses API JSON payload into :class:`NativeCompletionResponse`."""
    text_parts: List[str] = []
    reasoning_parts: List[str] = []
    tool_calls: List[NativeToolCall] = []

    for item in payload.get("output") or []:
        if not isinstance(item, Mapping):
            continue
        itype = str(item.get("type") or "")
        if itype == "message":
            for part in item.get("content") or []:
                if not isinstance(part, Mapping):
                    continue
                if part.get("type") in {"output_text", "text"} and part.get("text"):
                    text_parts.append(str(part["text"]))
        elif itype == "function_call":
            idx = len(tool_calls)
            args = item.get("arguments")
            args_str = args if isinstance(args, str) else json.dumps(args or {}, ensure_ascii=False)
            tool_calls.append(
                NativeToolCall(
                    id=str(item.get("call_id") or item.get("id") or f"call_{idx}"),
                    index=idx,
                    function=NativeFunctionCall(
                        name=str(item.get("name") or ""),
                        arguments=args_str,
                    ),
                )
            )
        elif itype == "reasoning":
            for summary_item in item.get("summary") or []:
                if isinstance(summary_item, Mapping) and summary_item.get("text"):
                    reasoning_parts.append(str(summary_item["text"]))

    if not text_parts and isinstance(payload.get("output_text"), str) and payload.get("output_text"):
        text_parts.append(payload["output_text"])

    finish_reason = "tool_calls" if tool_calls else "stop"
    message = NativeMessage(
        role="assistant",
        content="\n".join(text_parts) if text_parts else None,
        tool_calls=tool_calls or None,
        reasoning_content="\n".join(reasoning_parts) if reasoning_parts else None,
    )

    return NativeCompletionResponse(
        id=str(payload.get("id") or f"resp-{uuid.uuid4().hex[:12]}"),
        model=str(payload.get("model") or default_model),
        choices=[NativeChoice(index=0, message=message, finish_reason=finish_reason)],
        usage=_normalize_usage(payload.get("usage")),
        created=int(payload.get("created_at") or time.time()),
        object="chat.completion",
    )


def _iter_responses_stream_chunks(
    byte_chunks: Iterable[bytes],
    *,
    default_model: str = "",
    provider: str = "openai",
) -> Iterator[NativeStreamChunk]:
    """Stream Responses API SSE frames as Chat Completions-compatible :class:`NativeStreamChunk`."""
    tool_index_by_key: Dict[str, int] = {}
    saw_tool_calls = False
    response_id = f"resp-{uuid.uuid4().hex[:12]}"
    model_name = default_model

    for event_name, data in iter_sse_json_events(byte_chunks):
        etype = str(data.get("type") or event_name or "")
        resp_obj = data.get("response") if isinstance(data.get("response"), Mapping) else None
        if resp_obj:
            response_id = str(resp_obj.get("id") or response_id)
            model_name = str(resp_obj.get("model") or model_name)

        if etype == "response.output_text.delta":
            delta_text = data.get("delta")
            if delta_text:
                yield NativeStreamChunk(
                    id=response_id,
                    model=model_name,
                    choices=[NativeChoice(index=0, delta=NativeMessage(content=str(delta_text)))],
                )
        elif etype in {"response.reasoning_summary_text.delta", "response.reasoning.delta"}:
            delta_reasoning = data.get("delta")
            if delta_reasoning:
                yield NativeStreamChunk(
                    id=response_id,
                    model=model_name,
                    choices=[NativeChoice(index=0, delta=NativeMessage(reasoning_content=str(delta_reasoning)))],
                )
        elif etype == "response.output_item.added":
            item = data.get("item")
            if isinstance(item, Mapping) and item.get("type") == "function_call":
                saw_tool_calls = True
                item_key = str(item.get("id") or data.get("output_index", len(tool_index_by_key)))
                tc_index = tool_index_by_key.setdefault(item_key, len(tool_index_by_key))
                call_id = str(item.get("call_id") or item.get("id") or f"call_{tc_index}")
                name = str(item.get("name") or "")
                initial_args = str(item.get("arguments") or "")
                yield NativeStreamChunk(
                    id=response_id,
                    model=model_name,
                    choices=[
                        NativeChoice(
                            index=0,
                            delta=NativeMessage(
                                tool_calls=[
                                    NativeToolCall(
                                        id=call_id,
                                        index=tc_index,
                                        function=NativeFunctionCall(name=name, arguments=initial_args),
                                    )
                                ]
                            ),
                        )
                    ],
                )
        elif etype == "response.function_call_arguments.delta":
            item_key = str(data.get("item_id") or data.get("output_index", 0))
            tc_index = tool_index_by_key.setdefault(item_key, len(tool_index_by_key))
            delta_args = str(data.get("delta") or "")
            if delta_args:
                saw_tool_calls = True
                yield NativeStreamChunk(
                    id=response_id,
                    model=model_name,
                    choices=[
                        NativeChoice(
                            index=0,
                            delta=NativeMessage(
                                tool_calls=[
                                    NativeToolCall(
                                        index=tc_index,
                                        function=NativeFunctionCall(arguments=delta_args),
                                    )
                                ]
                            ),
                        )
                    ],
                )
        elif etype == "response.completed":
            usage = _normalize_usage((resp_obj or {}).get("usage") or data.get("usage"))
            finish_reason = "tool_calls" if saw_tool_calls else "stop"
            yield NativeStreamChunk(
                id=response_id,
                model=model_name,
                choices=[NativeChoice(index=0, delta=NativeMessage(), finish_reason=finish_reason)],
                usage=usage,
            )
        elif etype in {"error", "response.failed"}:
            err = (resp_obj or {}).get("error") or data.get("error") or data
            raise NativeAPIError(f"Responses stream error: {err}", provider=provider)


# ============================================================
# Protocol Adapter Entrypoints (reused by NativeUnifiedRouter)
# ============================================================


def prepare_openai_request(
    entry: DeploymentEntry,
    messages: List[Dict[str, Any]],
    stream: bool,
    kwargs: Mapping[str, Any],
    *,
    default_timeout: float = 120.0,
) -> PreparedRequest:
    """Build URL, headers, JSON payload, and timeout for OpenAI Chat or Responses protocol."""
    url = resolve_openai_endpoint_url(entry.api_base, entry.protocol)
    headers: Dict[str, str] = {"Content-Type": "application/json"}
    headers.update(entry.extra_headers)
    merge_header_overrides(headers, kwargs)

    api_key = entry.api_key or kwargs.get("api_key")
    if api_key and not has_header_case_insensitive(headers, "authorization"):
        headers["Authorization"] = f"Bearer {api_key}"

    filtered_kwargs = {k: v for k, v in kwargs.items() if k not in _FILTERED_REQUEST_KWARGS}
    if entry.protocol == "openai_responses":
        payload = build_responses_api_payload(
            wire_model=entry.wire_model,
            messages=messages,
            stream=stream,
            deployment_extra_body=entry.extra_body,
            **filtered_kwargs,
        )
    else:
        payload = build_chat_completions_payload(
            wire_model=entry.wire_model,
            messages=messages,
            stream=stream,
            deployment_extra_body=entry.extra_body,
            **filtered_kwargs,
        )

    req_timeout = float(kwargs.get("timeout") or entry.timeout or default_timeout)
    return url, headers, payload, req_timeout


def parse_openai_response(entry: DeploymentEntry, payload: Mapping[str, Any]) -> NativeCompletionResponse:
    """Parse OpenAI Chat Completions or Responses JSON response."""
    if entry.protocol == "openai_responses":
        return parse_responses_api_response(payload, default_model=entry.wire_model)
    return parse_chat_completion_response(payload, default_model=entry.wire_model)


def iter_openai_stream_chunks(
    entry: DeploymentEntry,
    byte_chunks: Iterable[bytes],
) -> Iterator[NativeStreamChunk]:
    """Iterate normalized stream chunks for OpenAI Chat Completions or Responses SSE."""
    if entry.protocol == "openai_responses":
        return _iter_responses_stream_chunks(
            byte_chunks,
            default_model=entry.wire_model,
            provider=entry.provider,
        )
    return (
        chunk
        for _ev, data in iter_sse_json_events(byte_chunks)
        if (chunk := parse_chat_completion_stream_chunk(data, default_model=entry.wire_model)) is not None
    )


# ============================================================
# Native HTTPX OpenAI Router & Transport (Wave 2 compatibility)
# ============================================================


class NativeOpenAIRouter:
    """Pooled HTTPX execution router supporting Chat Completions & Responses protocols."""

    def __init__(
        self,
        model_list: Optional[List[Dict[str, Any]]] = None,
        *,
        pool: Optional[DeploymentPool] = None,
        http_transport: Optional[httpx.BaseTransport] = None,
        timeout: float = 120.0,
        num_retries: int = 2,
        cooldown_time: float = 30.0,
        clock: Callable[[], float] = time.monotonic,
        sleep_fn: Optional[Callable[[float], None]] = None,
        routing_strategy: Optional[str] = None,
        allowed_fails: Optional[int] = None,
        **_extra_kwargs: Any,
    ) -> None:
        del routing_strategy, allowed_fails, _extra_kwargs
        self.model_list: List[Dict[str, Any]] = list(model_list or [])
        self._http_transport = http_transport
        self._timeout = float(timeout)
        self._num_retries = max(0, int(num_retries))
        self._sleep_fn = sleep_fn
        if pool is not None:
            self._pool = pool
        else:
            entries = self._entries_from_model_list(self.model_list)
            self._pool = DeploymentPool(
                entries,
                clock=clock,
                base_cooldown_seconds=max(1.0, float(cooldown_time)),
            )

    @staticmethod
    def _entries_from_model_list(model_list: List[Dict[str, Any]]) -> List[DeploymentEntry]:
        entries: List[DeploymentEntry] = []
        for idx, raw_entry in enumerate(model_list):
            if not isinstance(raw_entry, Mapping):
                continue
            params = raw_entry.get("litellm_params") or {}
            if not isinstance(params, Mapping):
                params = {}
            raw_model = str(params.get("model") or raw_entry.get("model_name") or "").strip()
            alias = str(raw_entry.get("model_name") or raw_model).strip()
            provider, wire_model = strip_provider_prefix(raw_model)
            api_base = str(
                params.get("api_base")
                or params.get("base_url")
                or DEFAULT_PROVIDER_BASES.get(provider)
                or DEFAULT_PROVIDER_BASES["openai"]
            ).strip()
            protocol = resolve_openai_wire_protocol(
                raw_model,
                api_base=api_base,
                wire_protocol=params.get("wire_protocol"),
            )
            extra_headers: Dict[str, str] = {}
            merge_header_overrides(extra_headers, params)
            extra_body = dict(params.get("extra_body")) if isinstance(params.get("extra_body"), Mapping) else {}
            timeout_val = params.get("timeout")
            entries.append(
                DeploymentEntry(
                    deployment_id=f"{alias}:{idx}",
                    model_name=alias,
                    wire_model=wire_model,
                    api_base=api_base,
                    api_key=params.get("api_key"),
                    protocol=protocol,
                    provider=provider,
                    extra_headers=extra_headers,
                    extra_body=extra_body,
                    priority=int((raw_entry.get("model_info") or {}).get("priority", idx)),
                    timeout=float(timeout_val) if timeout_val is not None else None,
                )
            )
        return entries

    @property
    def pool(self) -> DeploymentPool:
        """Expose underlying :class:`DeploymentPool` for diagnostics/health checks."""
        return self._pool

    def _ephemeral_entry(self, model: str, kwargs: Mapping[str, Any]) -> DeploymentEntry:
        provider, wire_model = strip_provider_prefix(model)
        client_api_key, client_base_url, _client_http = extract_client_overrides(kwargs)
        api_base = str(
            kwargs.get("api_base")
            or kwargs.get("base_url")
            or client_base_url
            or DEFAULT_PROVIDER_BASES.get(provider)
            or DEFAULT_PROVIDER_BASES["openai"]
        ).strip()
        protocol = resolve_openai_wire_protocol(
            model,
            api_base=api_base,
            wire_protocol=kwargs.get("wire_protocol"),
        )
        extra_headers: Dict[str, str] = {}
        merge_header_overrides(extra_headers, kwargs)
        return DeploymentEntry(
            deployment_id=f"ephemeral:{model}",
            model_name=model,
            wire_model=wire_model,
            api_base=api_base,
            api_key=kwargs.get("api_key") or client_api_key,
            protocol=protocol,
            provider=provider,
            extra_headers=extra_headers,
            extra_body={},
            timeout=float(kwargs["timeout"]) if kwargs.get("timeout") is not None else None,
        )

    def completion(self, *, model: str, messages: List[Dict[str, Any]], stream: bool = False, **kwargs: Any) -> Any:
        """Execute pooled completion across healthy deployments (non-stream or streaming)."""
        req_kwargs = dict(kwargs)
        raw_retries = req_kwargs.pop("num_retries", self._num_retries)
        effective_retries = max(0, int(raw_retries if raw_retries is not None else self._num_retries))
        _, _, client_http = extract_client_overrides(req_kwargs)
        candidates = self._pool.select_candidates(model)
        using_pool = bool(candidates)
        if not candidates:
            candidates = [self._ephemeral_entry(model, req_kwargs)]

        def _prepare(
            entry: DeploymentEntry,
            msgs: List[Dict[str, Any]],
            is_stream: bool,
            call_opts: Mapping[str, Any],
        ) -> PreparedRequest:
            return prepare_openai_request(entry, msgs, is_stream, call_opts, default_timeout=self._timeout)

        if stream:
            return stream_pooled_completion(
                candidates=candidates,
                pool=self._pool,
                using_pool=using_pool,
                messages=messages,
                kwargs=req_kwargs,
                prepare_request_fn=_prepare,
                iter_stream_fn=iter_openai_stream_chunks,
                http_transport=self._http_transport,
                http_client=client_http,
                request_model=model,
                num_retries=effective_retries,
                sleep_fn=self._sleep_fn,
                cancel_check=raise_if_stock_cancelled,
            )

        return execute_pooled_completion(
            candidates=candidates,
            pool=self._pool,
            using_pool=using_pool,
            messages=messages,
            kwargs=req_kwargs,
            prepare_request_fn=_prepare,
            parse_response_fn=parse_openai_response,
            http_transport=self._http_transport,
            http_client=client_http,
            request_model=model,
            num_retries=effective_retries,
            sleep_fn=self._sleep_fn,
            cancel_check=raise_if_stock_cancelled,
        )


class NativeOpenAITransport:
    """Native ``httpx`` OpenAI Chat Completions & Responses transport implementing ``LLMTransport``."""

    _EXCEPTION_MAP: Dict[str, type[BaseException]] = {
        "RateLimitError": NativeRateLimitError,
        "ContextWindowExceededError": NativeContextWindowExceededError,
        "AuthenticationError": NativeAuthenticationError,
        "BadRequestError": NativeBadRequestError,
        "APIError": NativeAPIError,
    }

    def __init__(
        self,
        *,
        http_transport: Optional[httpx.BaseTransport] = None,
        fallback_transport: Optional[Any] = None,
        clock: Callable[[], float] = time.monotonic,
        sleep_fn: Optional[Callable[[float], None]] = None,
        default_timeout: float = 120.0,
    ) -> None:
        self._http_transport = http_transport
        self._fallback_transport = fallback_transport
        self._clock = clock
        self._sleep_fn = sleep_fn
        self._default_timeout = float(default_timeout)
        self._registered_model_costs: Dict[str, Any] = {}

    def completion(self, **kwargs: Any) -> Any:
        """Execute completion via native HTTPX OpenAI path or delegate unsupported providers."""
        model = str(kwargs.get("model") or "").strip()
        api_base = kwargs.get("api_base") or kwargs.get("base_url")
        custom_provider = kwargs.get("custom_llm_provider")
        if not supports_native_openai_provider(
            model,
            api_base=api_base,
            custom_llm_provider=custom_provider,
        ):
            if self._fallback_transport is not None:
                return self._fallback_transport.completion(**kwargs)
            raise NativeBadRequestError(
                f"NativeOpenAITransport does not support provider for model '{model}' without fallback_transport",
                status_code=400,
                provider=strip_provider_prefix(model)[0],
            )

        call_kwargs = dict(kwargs)
        raw_retries = call_kwargs.pop("num_retries", 0)
        effective_retries = max(0, int(raw_retries if raw_retries is not None else 0))
        router = NativeOpenAIRouter(
            http_transport=self._http_transport,
            timeout=float(call_kwargs.get("timeout") or self._default_timeout),
            num_retries=effective_retries,
            clock=self._clock,
            sleep_fn=self._sleep_fn,
        )
        messages = call_kwargs.pop("messages", [])
        stream = bool(call_kwargs.pop("stream", False))
        call_kwargs.pop("model", None)
        return router.completion(model=model, messages=messages, stream=stream, **call_kwargs)

    def create_router(self, model_list: List[Dict[str, Any]], **kwargs: Any) -> Any:
        """Build a pooled :class:`NativeOpenAIRouter` when deployments use OpenAI-family protocols."""
        all_openai = all(
            supports_native_openai_provider(
                str((entry.get("litellm_params") or {}).get("model") or entry.get("model_name") or ""),
                api_base=(entry.get("litellm_params") or {}).get("api_base"),
                custom_llm_provider=(entry.get("litellm_params") or {}).get("custom_llm_provider"),
            )
            for entry in (model_list or [])
            if isinstance(entry, Mapping)
        )
        if not all_openai and self._fallback_transport is not None:
            return self._fallback_transport.create_router(model_list, **kwargs)
        return NativeOpenAIRouter(
            model_list=model_list,
            http_transport=self._http_transport,
            timeout=float(kwargs.get("timeout") or self._default_timeout),
            num_retries=int(kwargs.get("num_retries", 2)),
            cooldown_time=float(kwargs.get("cooldown_time", 30.0)),
            clock=self._clock,
        )

    def can_register_model(self) -> bool:
        return True

    def register_model(self, model_cost: Dict[str, Any]) -> None:
        if isinstance(model_cost, Mapping):
            self._registered_model_costs.update(model_cost)

    def get_model_cost(self) -> Dict[str, Any]:
        return dict(self._registered_model_costs)

    def token_counter(self, *, model: str, text: str) -> int:
        raw = str(text or "")
        if not raw:
            return 0
        return max(1, (len(raw) + 2) // 3)

    def get_model_providers(self) -> frozenset[str]:
        return NATIVE_OPENAI_PROVIDERS

    def disable_streaming_logging(self) -> None:
        return None

    def silence_logs(self) -> None:
        return None

    def resolve_exception(self, name: str) -> type[BaseException]:
        if name in self._EXCEPTION_MAP:
            return self._EXCEPTION_MAP[name]
        if self._fallback_transport is not None:
            return self._fallback_transport.resolve_exception(name)
        return NativeAPIError
