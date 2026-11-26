# -*- coding: utf-8 -*-
"""
===================================
Native HTTPX Anthropic Messages API Adapter
===================================

Issue #2622 Phase 2b: direct ``/v1/messages`` serializer, SSE parser, extended
thinking (``thinking`` / ``redacted_thinking``) block preservation, Vision base64/URL
parts, strict role alternation merging, and Anthropic prompt-cache token accounting.
"""

from __future__ import annotations

import json
import time
from typing import Any, Dict, Iterable, Iterator, List, Mapping, Optional
import uuid

from src.llm.native_types import (
    DEFAULT_ANTHROPIC_BASE,
    NativeAPIError,
    NativeChoice,
    NativeCompletionResponse,
    NativeFunctionCall,
    NativeMessage,
    NativeStreamChunk,
    NativeToolCall,
    NativeUsage,
    PreparedRequest,
    extract_tool_arguments_dict,
    has_header_case_insensitive,
    merge_header_overrides,
    parse_data_url,
)
from src.llm.pool import DeploymentEntry
from src.llm.sse import iter_sse_json_events

ANTHROPIC_DEFAULT_VERSION = "2023-06-01"

_STOP_REASON_MAP = {
    "end_turn": "stop",
    "stop_sequence": "stop",
    "max_tokens": "length",
    "tool_use": "tool_calls",
    "refusal": "content_filter",
    "pause_turn": "stop",
}


def resolve_anthropic_endpoint(api_base: Optional[str]) -> str:
    """Resolve Anthropic ``/v1/messages`` URL without duplicating ``/v1``."""
    base = (api_base or DEFAULT_ANTHROPIC_BASE).strip().rstrip("/")
    if base.endswith("/v1/messages") or base.endswith("/messages"):
        return base
    if base.endswith("/v1"):
        return f"{base}/messages"
    return f"{base}/v1/messages"


def _map_anthropic_stop_reason(
    stop_reason: Optional[str],
    *,
    has_tool_calls: bool = False,
) -> Optional[str]:
    if stop_reason is None:
        return "tool_calls" if has_tool_calls else None
    key = str(stop_reason).strip().lower()
    if key in _STOP_REASON_MAP:
        return _STOP_REASON_MAP[key]
    return "tool_calls" if has_tool_calls else "stop"


def parse_anthropic_usage(raw_usage: Any) -> Optional[NativeUsage]:
    """Normalize Anthropic usage fields preserving ``input_tokens`` and cache counters for ``usage.py``."""
    if not isinstance(raw_usage, Mapping):
        return None
    raw_input = raw_usage.get("input_tokens")
    raw_output = raw_usage.get("output_tokens")
    cache_read = raw_usage.get("cache_read_input_tokens")
    cache_creation = raw_usage.get("cache_creation_input_tokens")

    uncached = int(raw_input) if raw_input is not None else None
    output_tokens = int(raw_output) if raw_output is not None else None
    read_val = int(cache_read) if cache_read is not None else 0
    write_val = int(cache_creation) if cache_creation is not None else 0

    prompt_tokens: Optional[int] = None
    if uncached is not None:
        prompt_tokens = uncached + read_val + write_val
    elif raw_usage.get("prompt_tokens") is not None:
        prompt_tokens = int(raw_usage["prompt_tokens"])

    total_tokens: Optional[int] = None
    if prompt_tokens is not None and output_tokens is not None:
        total_tokens = prompt_tokens + output_tokens
    elif raw_usage.get("total_tokens") is not None:
        total_tokens = int(raw_usage["total_tokens"])

    prompt_details: Optional[Dict[str, Any]] = None
    if cache_read is not None:
        prompt_details = {"cached_tokens": read_val}

    extra: Dict[str, Any] = {}
    if uncached is not None:
        extra["input_tokens"] = uncached
    if output_tokens is not None:
        extra["output_tokens"] = output_tokens
    if cache_read is not None:
        extra["cache_read_input_tokens"] = read_val
    if cache_creation is not None:
        extra["cache_creation_input_tokens"] = write_val

    return NativeUsage(
        prompt_tokens=prompt_tokens,
        completion_tokens=output_tokens,
        total_tokens=total_tokens,
        prompt_tokens_details=prompt_details,
        extra=extra,
    )


def _convert_part_to_anthropic(part: Any) -> Optional[Dict[str, Any]]:
    if isinstance(part, str):
        return {"type": "text", "text": part} if part else None
    if not isinstance(part, Mapping):
        return None
    ptype = str(part.get("type") or "text").strip().lower()
    block: Optional[Dict[str, Any]] = None

    if ptype in {"text", "input_text", "output_text"}:
        text = str(part.get("text") or "")
        block = {"type": "text", "text": text}
    elif ptype == "image_url":
        img = part.get("image_url")
        url = img.get("url") if isinstance(img, Mapping) else img
        url_str = str(url or "").strip()
        if url_str:
            parsed_data = parse_data_url(url_str)
            if parsed_data is not None:
                mime_type, b64_data = parsed_data
                block = {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": mime_type,
                        "data": b64_data,
                    },
                }
            else:
                block = {
                    "type": "image",
                    "source": {"type": "url", "url": url_str},
                }
    elif ptype in {"image", "thinking", "redacted_thinking", "tool_use", "tool_result"}:
        block = dict(part)

    if block is not None and isinstance(part.get("cache_control"), Mapping):
        block["cache_control"] = dict(part["cache_control"])
    return block


def _ensure_anthropic_block_list(content: Any) -> List[Dict[str, Any]]:
    if isinstance(content, list):
        return [dict(item) for item in content if isinstance(item, Mapping)]
    if isinstance(content, str) and content:
        return [{"type": "text", "text": content}]
    return []


def _append_alternating_turn(
    turns: List[Dict[str, Any]],
    *,
    role: str,
    blocks: List[Dict[str, Any]],
) -> None:
    if not blocks:
        return
    if turns and turns[-1]["role"] == role:
        merged = _ensure_anthropic_block_list(turns[-1]["content"]) + blocks
        turns[-1]["content"] = merged
        return
    turns.append({"role": role, "content": blocks})


def _convert_anthropic_tools(tools: Any) -> Optional[List[Dict[str, Any]]]:
    if not isinstance(tools, list) or not tools:
        return None
    converted: List[Dict[str, Any]] = []
    for tool in tools:
        if not isinstance(tool, Mapping):
            continue
        if tool.get("type") == "function" and isinstance(tool.get("function"), Mapping):
            fn = tool["function"]
            entry: Dict[str, Any] = {
                "name": str(fn.get("name") or ""),
                "description": str(fn.get("description") or ""),
                "input_schema": (
                    dict(fn["parameters"])
                    if isinstance(fn.get("parameters"), Mapping)
                    else {"type": "object", "properties": {}}
                ),
            }
            cache_ctrl = tool.get("cache_control") or fn.get("cache_control")
            if isinstance(cache_ctrl, Mapping):
                entry["cache_control"] = dict(cache_ctrl)
            converted.append(entry)
        elif "name" in tool and "input_schema" in tool:
            converted.append(dict(tool))
    return converted or None


def _convert_anthropic_tool_choice(tool_choice: Any) -> Optional[Dict[str, Any]]:
    if tool_choice is None:
        return None
    if isinstance(tool_choice, str):
        choice = tool_choice.strip().lower()
        if choice == "auto":
            return {"type": "auto"}
        if choice in {"required", "any"}:
            return {"type": "any"}
        if choice == "none":
            return {"type": "none"}
        return None
    if isinstance(tool_choice, Mapping):
        if tool_choice.get("type") == "function" and isinstance(tool_choice.get("function"), Mapping):
            fn_name = tool_choice["function"].get("name")
            if fn_name:
                return {"type": "tool", "name": str(fn_name)}
        return dict(tool_choice)
    return None


def build_anthropic_payload(
    *,
    wire_model: str,
    messages: List[Dict[str, Any]],
    stream: bool = False,
    deployment_extra_body: Optional[Mapping[str, Any]] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Translate OpenAI Chat-style messages/tools/params into an Anthropic ``/v1/messages`` JSON body."""
    system_blocks: List[Dict[str, Any]] = []
    has_system_structured = False
    turns: List[Dict[str, Any]] = []

    for msg in messages:
        if not isinstance(msg, Mapping):
            continue
        role = str(msg.get("role") or "user").strip().lower()

        if role in {"system", "developer"}:
            raw_sys = msg.get("content")
            msg_cache = msg.get("cache_control") if isinstance(msg.get("cache_control"), Mapping) else None
            if isinstance(raw_sys, str):
                if raw_sys.strip():
                    blk: Dict[str, Any] = {"type": "text", "text": raw_sys.strip()}
                    if msg_cache:
                        blk["cache_control"] = dict(msg_cache)
                        has_system_structured = True
                    system_blocks.append(blk)
            elif isinstance(raw_sys, list):
                has_system_structured = True
                for item in raw_sys:
                    converted = _convert_part_to_anthropic(item)
                    if converted is not None:
                        system_blocks.append(converted)
            continue

        if role == "tool":
            call_id = str(msg.get("tool_call_id") or "")
            raw_out = msg.get("content")
            if isinstance(raw_out, list):
                tool_content: Any = [
                    blk for item in raw_out if (blk := _convert_part_to_anthropic(item)) is not None
                ]
            elif isinstance(raw_out, str):
                tool_content = raw_out
            else:
                tool_content = json.dumps(raw_out if raw_out is not None else "", ensure_ascii=False)
            result_block: Dict[str, Any] = {
                "type": "tool_result",
                "tool_use_id": call_id,
                "content": tool_content,
            }
            if msg.get("is_error"):
                result_block["is_error"] = True
            if isinstance(msg.get("cache_control"), Mapping):
                result_block["cache_control"] = dict(msg["cache_control"])
            _append_alternating_turn(turns, role="user", blocks=[result_block])
            continue

        if role == "assistant":
            thinking_front: List[Dict[str, Any]] = []
            # Extended thinking requires thinking/redacted_thinking blocks before tool_use/text.
            for source_key in ("provider_blocks", "thinking_blocks"):
                raw_pblocks = msg.get(source_key)
                if isinstance(raw_pblocks, list):
                    for pb in raw_pblocks:
                        if isinstance(pb, Mapping) and pb.get("type") in {"thinking", "redacted_thinking"}:
                            thinking_front.append(dict(pb))
                    if thinking_front:
                        break

            other_blocks: List[Dict[str, Any]] = []
            raw_content = msg.get("content")
            if isinstance(raw_content, str):
                if raw_content:
                    other_blocks.append({"type": "text", "text": raw_content})
            elif isinstance(raw_content, list):
                has_explicit_thinking = bool(thinking_front)
                for part in raw_content:
                    converted = _convert_part_to_anthropic(part)
                    if converted is None:
                        continue
                    if converted.get("type") in {"thinking", "redacted_thinking"}:
                        if not has_explicit_thinking:
                            thinking_front.append(converted)
                    else:
                        other_blocks.append(converted)

            blocks: List[Dict[str, Any]] = thinking_front + other_blocks

            for tc in msg.get("tool_calls") or []:
                if not isinstance(tc, Mapping):
                    continue
                fn = tc.get("function") or {}
                fn_name = str(fn.get("name") or "") if isinstance(fn, Mapping) else ""
                raw_args = fn.get("arguments") if isinstance(fn, Mapping) else {}
                blocks.append(
                    {
                        "type": "tool_use",
                        "id": str(tc.get("id") or f"toolu_{uuid.uuid4().hex[:12]}"),
                        "name": fn_name,
                        "input": extract_tool_arguments_dict(raw_args),
                    }
                )

            _append_alternating_turn(turns, role="assistant", blocks=blocks)
            continue

        user_blocks: List[Dict[str, Any]] = []
        raw_content = msg.get("content")
        if isinstance(raw_content, str):
            if raw_content or not user_blocks:
                blk = {"type": "text", "text": raw_content}
                if isinstance(msg.get("cache_control"), Mapping):
                    blk["cache_control"] = dict(msg["cache_control"])
                user_blocks.append(blk)
        elif isinstance(raw_content, list):
            for part in raw_content:
                converted = _convert_part_to_anthropic(part)
                if converted is not None:
                    user_blocks.append(converted)
        _append_alternating_turn(turns, role="user", blocks=user_blocks)

    max_tokens = (
        kwargs.get("max_tokens")
        or kwargs.get("max_completion_tokens")
        or kwargs.get("max_output_tokens")
        or 4096
    )

    merged_extra: Dict[str, Any] = {}
    if isinstance(deployment_extra_body, Mapping):
        merged_extra.update(deployment_extra_body)
    if isinstance(kwargs.get("extra_body"), Mapping):
        merged_extra.update(kwargs["extra_body"])

    thinking_cfg = kwargs.get("thinking") or merged_extra.get("thinking")
    if isinstance(thinking_cfg, Mapping) and str(thinking_cfg.get("type") or "").lower() == "enabled":
        budget = thinking_cfg.get("budget_tokens")
        if isinstance(budget, int) and int(max_tokens) <= budget:
            max_tokens = budget + 1024

    body: Dict[str, Any] = {
        "model": wire_model,
        "messages": turns,
        "max_tokens": int(max_tokens),
        "stream": bool(stream),
    }

    if system_blocks:
        if has_system_structured:
            body["system"] = system_blocks
        else:
            body["system"] = "\n\n".join(str(b.get("text") or "") for b in system_blocks if b.get("text"))

    thinking_enabled = (
        isinstance(thinking_cfg, Mapping)
        and str(thinking_cfg.get("type") or "").lower() == "enabled"
    )
    if kwargs.get("temperature") is not None:
        temp_val = float(kwargs["temperature"])
        if not thinking_enabled or temp_val == 1.0:
            body["temperature"] = kwargs["temperature"]
    if kwargs.get("top_p") is not None and not thinking_enabled:
        body["top_p"] = kwargs["top_p"]
    if kwargs.get("top_k") is not None:
        body["top_k"] = kwargs["top_k"]

    stop_val = kwargs.get("stop_sequences") if kwargs.get("stop_sequences") is not None else kwargs.get("stop")
    if isinstance(stop_val, str) and stop_val:
        body["stop_sequences"] = [stop_val]
    elif isinstance(stop_val, list) and stop_val:
        body["stop_sequences"] = [str(s) for s in stop_val]

    anthropic_tools = _convert_anthropic_tools(kwargs.get("tools"))
    if anthropic_tools:
        body["tools"] = anthropic_tools
        converted_choice = _convert_anthropic_tool_choice(kwargs.get("tool_choice"))
        if converted_choice is not None:
            body["tool_choice"] = converted_choice

    if isinstance(thinking_cfg, Mapping):
        body["thinking"] = dict(thinking_cfg)

    for key, value in merged_extra.items():
        if value is not None and key != "thinking":
            body[key] = value

    return body


def parse_anthropic_response(
    payload: Mapping[str, Any],
    *,
    default_model: str = "",
) -> NativeCompletionResponse:
    """Normalize an Anthropic ``/v1/messages`` JSON payload into :class:`NativeCompletionResponse`."""
    text_parts: List[str] = []
    reasoning_parts: List[str] = []
    thinking_blocks: List[Dict[str, Any]] = []
    tool_calls: List[NativeToolCall] = []

    for block in payload.get("content") or []:
        if not isinstance(block, Mapping):
            continue
        btype = str(block.get("type") or "")
        if btype == "text":
            if block.get("text") is not None:
                text_parts.append(str(block["text"]))
        elif btype == "thinking":
            thinking_blocks.append(dict(block))
            if block.get("thinking"):
                reasoning_parts.append(str(block["thinking"]))
        elif btype == "redacted_thinking":
            thinking_blocks.append(dict(block))
        elif btype == "tool_use":
            idx = len(tool_calls)
            raw_input = block.get("input")
            args_str = raw_input if isinstance(raw_input, str) else json.dumps(raw_input or {}, ensure_ascii=False)
            tool_calls.append(
                NativeToolCall(
                    id=str(block.get("id") or f"toolu_{idx}"),
                    index=idx,
                    function=NativeFunctionCall(
                        name=str(block.get("name") or ""),
                        arguments=args_str,
                    ),
                )
            )

    finish_reason = _map_anthropic_stop_reason(
        payload.get("stop_reason"),
        has_tool_calls=bool(tool_calls),
    )
    message = NativeMessage(
        role=str(payload.get("role") or "assistant"),
        content="\n".join(text_parts) if text_parts else None,
        tool_calls=tool_calls or None,
        reasoning_content="\n".join(reasoning_parts) if reasoning_parts else None,
        thinking_blocks=thinking_blocks or None,
    )
    return NativeCompletionResponse(
        id=str(payload.get("id") or f"msg_{uuid.uuid4().hex[:12]}"),
        model=str(payload.get("model") or default_model),
        choices=[NativeChoice(index=0, message=message, finish_reason=finish_reason)],
        usage=parse_anthropic_usage(payload.get("usage")),
        created=int(time.time()),
        object="chat.completion",
    )


def iter_anthropic_stream_chunks(
    byte_chunks: Iterable[bytes],
    *,
    default_model: str = "",
    provider: str = "anthropic",
) -> Iterator[NativeStreamChunk]:
    """Stream Anthropic Messages SSE events into normalized :class:`NativeStreamChunk` frames."""
    msg_id = f"msg_{uuid.uuid4().hex[:12]}"
    model_name = default_model
    block_idx_to_tool_idx: Dict[int, int] = {}
    thinking_accum: Dict[int, Dict[str, Any]] = {}
    saw_tool_calls = False
    emitted_finish = False
    raw_usage_state: Dict[str, Any] = {}

    for event_name, data in iter_sse_json_events(byte_chunks):
        etype = str(data.get("type") or event_name or "")

        if etype == "message_start":
            message_obj = data.get("message")
            if isinstance(message_obj, Mapping):
                msg_id = str(message_obj.get("id") or msg_id)
                model_name = str(message_obj.get("model") or model_name)
                if isinstance(message_obj.get("usage"), Mapping):
                    raw_usage_state.update(message_obj["usage"])
            continue

        if etype == "content_block_start":
            block_idx = int(data.get("index", 0))
            block = data.get("content_block")
            if not isinstance(block, Mapping):
                continue
            btype = str(block.get("type") or "")
            if btype == "tool_use":
                saw_tool_calls = True
                tc_idx = len(block_idx_to_tool_idx)
                block_idx_to_tool_idx[block_idx] = tc_idx
                raw_input = block.get("input")
                initial_args = json.dumps(raw_input, ensure_ascii=False) if raw_input else ""
                yield NativeStreamChunk(
                    id=msg_id,
                    model=model_name,
                    choices=[
                        NativeChoice(
                            index=0,
                            delta=NativeMessage(
                                tool_calls=[
                                    NativeToolCall(
                                        id=str(block.get("id") or f"toolu_{tc_idx}"),
                                        index=tc_idx,
                                        function=NativeFunctionCall(
                                            name=str(block.get("name") or ""),
                                            arguments=initial_args,
                                        ),
                                    )
                                ]
                            ),
                        )
                    ],
                )
            elif btype == "thinking":
                thinking_accum[block_idx] = {
                    "type": "thinking",
                    "thinking": str(block.get("thinking") or ""),
                    "signature": str(block.get("signature") or ""),
                }
            elif btype == "redacted_thinking":
                thinking_accum[block_idx] = dict(block)
            continue

        if etype == "content_block_delta":
            block_idx = int(data.get("index", 0))
            delta = data.get("delta")
            if not isinstance(delta, Mapping):
                continue
            dtype = str(delta.get("type") or "")
            if dtype == "text_delta":
                text_delta = delta.get("text")
                if text_delta:
                    yield NativeStreamChunk(
                        id=msg_id,
                        model=model_name,
                        choices=[NativeChoice(index=0, delta=NativeMessage(content=str(text_delta)))],
                    )
            elif dtype == "thinking_delta":
                t_delta = delta.get("thinking")
                if t_delta:
                    if block_idx in thinking_accum:
                        thinking_accum[block_idx]["thinking"] += str(t_delta)
                    yield NativeStreamChunk(
                        id=msg_id,
                        model=model_name,
                        choices=[NativeChoice(index=0, delta=NativeMessage(reasoning_content=str(t_delta)))],
                    )
            elif dtype == "signature_delta":
                sig = delta.get("signature")
                if sig and block_idx in thinking_accum:
                    thinking_accum[block_idx]["signature"] += str(sig)
            elif dtype == "input_json_delta":
                partial_json = str(delta.get("partial_json") or "")
                if partial_json:
                    tc_idx = block_idx_to_tool_idx.setdefault(block_idx, len(block_idx_to_tool_idx))
                    saw_tool_calls = True
                    yield NativeStreamChunk(
                        id=msg_id,
                        model=model_name,
                        choices=[
                            NativeChoice(
                                index=0,
                                delta=NativeMessage(
                                    tool_calls=[
                                        NativeToolCall(
                                            index=tc_idx,
                                            function=NativeFunctionCall(arguments=partial_json),
                                        )
                                    ]
                                ),
                            )
                        ],
                    )
            continue

        if etype == "content_block_stop":
            block_idx = int(data.get("index", 0))
            final_block = thinking_accum.pop(block_idx, None)
            if final_block is not None:
                yield NativeStreamChunk(
                    id=msg_id,
                    model=model_name,
                    choices=[
                        NativeChoice(
                            index=0,
                            delta=NativeMessage(
                                thinking_blocks=[dict(final_block)],
                            ),
                        )
                    ],
                )
            continue

        if etype == "message_delta":
            if isinstance(data.get("usage"), Mapping):
                raw_usage_state.update(data["usage"])
            delta_obj = data.get("delta") if isinstance(data.get("delta"), Mapping) else {}
            mapped_finish = _map_anthropic_stop_reason(
                delta_obj.get("stop_reason"),
                has_tool_calls=saw_tool_calls,
            )
            emitted_finish = mapped_finish is not None
            yield NativeStreamChunk(
                id=msg_id,
                model=model_name,
                choices=[NativeChoice(index=0, delta=NativeMessage(), finish_reason=mapped_finish)],
                usage=parse_anthropic_usage(raw_usage_state) if raw_usage_state else None,
            )
            continue

        if etype == "message_stop":
            if not emitted_finish:
                emitted_finish = True
                yield NativeStreamChunk(
                    id=msg_id,
                    model=model_name,
                    choices=[
                        NativeChoice(
                            index=0,
                            delta=NativeMessage(),
                            finish_reason="tool_calls" if saw_tool_calls else "stop",
                        )
                    ],
                    usage=parse_anthropic_usage(raw_usage_state) if raw_usage_state else None,
                )
            continue

        if etype == "error":
            err = data.get("error") or data
            raise NativeAPIError(f"Anthropic stream error: {err}", provider=provider)


def prepare_anthropic_request(
    entry: DeploymentEntry,
    messages: List[Dict[str, Any]],
    stream: bool,
    kwargs: Mapping[str, Any],
    *,
    default_timeout: float = 120.0,
) -> PreparedRequest:
    """Build URL, headers (``x-api-key`` + ``anthropic-version``), JSON body, and timeout."""
    url = resolve_anthropic_endpoint(entry.api_base)
    headers: Dict[str, str] = {
        "Content-Type": "application/json",
        "anthropic-version": ANTHROPIC_DEFAULT_VERSION,
    }
    headers.update(entry.extra_headers)
    merge_header_overrides(headers, kwargs)

    api_key = entry.api_key or kwargs.get("api_key")
    if (
        api_key
        and not has_header_case_insensitive(headers, "x-api-key")
        and not has_header_case_insensitive(headers, "authorization")
    ):
        headers["x-api-key"] = str(api_key)

    filtered_kwargs = {
        k: v
        for k, v in kwargs.items()
        if k not in {"wire_model", "messages", "stream", "deployment_extra_body", "client"}
    }
    payload = build_anthropic_payload(
        wire_model=entry.wire_model,
        messages=messages,
        stream=stream,
        deployment_extra_body=entry.extra_body,
        **filtered_kwargs,
    )
    req_timeout = float(kwargs.get("timeout") or entry.timeout or default_timeout)
    return url, headers, payload, req_timeout
