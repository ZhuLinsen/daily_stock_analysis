# -*- coding: utf-8 -*-
"""Native HTTPX Anthropic Messages API Adapter.

Pure prepare/parse/stream-iterator adapter for ``/v1/messages`` preserving
ordered ``provider_blocks`` (thinking + visible text), list-form system
``cache_control``, ``reasoning_effort`` thinking budgets, strict alternating
roles with leading user turn, and SSE ``message_stop`` completeness checks.
"""

from __future__ import annotations

import copy
import json
import logging
import time
from typing import Any, Callable, Dict, Iterable, Iterator, List, Mapping, Optional
import uuid

from src.llm.native_resolve import resolve_anthropic_endpoint_url, resolve_env_reference
from src.llm.native_types import (
    DeploymentSpec,
    NativeAPIError,
    NativeBadRequestError,
    NativeChoice,
    NativeCompletionResponse,
    NativeFunctionCall,
    NativeIncompleteStreamError,
    NativeMessage,
    NativeStreamChunk,
    NativeToolCall,
    NativeUsage,
    PreparedRequest,
    check_in_band_json_error,
    extract_tool_arguments_dict,
    has_header_case_insensitive,
    merge_header_overrides,
    parse_data_url,
    parse_strict_bool,
)
from src.llm.sse import iter_sse_json_events

logger = logging.getLogger(__name__)

ANTHROPIC_DEFAULT_VERSION = "2023-06-01"

_STOP_REASON_MAP = {
    "end_turn": "stop",
    "stop_sequence": "stop",
    "max_tokens": "length",
    "tool_use": "tool_calls",
    "refusal": "content_filter",
    "pause_turn": "stop",
}

_REASONING_EFFORT_BUDGETS: Dict[str, int] = {
    "low": 1024,
    "medium": 4096,
    "high": 8192,
}

_FILTERED_KWARGS = frozenset(
    {
        "model",
        "wire_model",
        "messages",
        "stream",
        "deployment_extra_body",
        "client",
        "api_surface",
        "wire_protocol",
        "dsa_channel_protocol",
        "api_key",
        "api_base",
        "base_url",
        "extra_headers",
        "headers",
        "default_headers",
        "custom_llm_provider",
        "timeout",
        "num_retries",
        "fallbacks",
        "metadata",
        "caching",
        "drop_params",
        "_dsa_deadline_monotonic",
        "_dsa_skip_sensitive_caller_headers",
        "_dsa_force_max_tokens",
        "_dsa_disable_stream_options",
        "_dsa_disable_response_format",
    }
)


def _merge_request_defaults(
    entry: DeploymentSpec,
    kwargs: Mapping[str, Any],
) -> Dict[str, Any]:
    merged: Dict[str, Any] = {}
    if isinstance(entry.request_defaults, Mapping):
        for k, v in entry.request_defaults.items():
            if v is not None:
                merged[k] = copy.deepcopy(v)
    for k, v in kwargs.items():
        if k in _FILTERED_KWARGS:
            continue
        if v is None and k == "response_format":
            merged.pop("response_format", None)
            continue
        if v is not None:
            merged[k] = v
    if kwargs.get("_dsa_disable_response_format"):
        merged.pop("response_format", None)
    return merged


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
    """Normalize Anthropic usage fields preserving ``input_tokens`` and cache counters."""
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
    """Convert an OpenAI/Anthropic content part into an Anthropic block, dropping empty text."""
    if isinstance(part, str):
        return {"type": "text", "text": part} if part != "" else None
    if not isinstance(part, Mapping):
        return None
    ptype = str(part.get("type") or "text").strip().lower()
    block: Optional[Dict[str, Any]] = None

    if ptype in {"text", "input_text", "output_text"}:
        text_val = str(part.get("text") or "")
        if not text_val:
            return None
        block = {"type": "text", "text": text_val}
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
        block = copy.deepcopy(dict(part))

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
            converted.append(copy.deepcopy(dict(tool)))
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


def _resolve_thinking_config(
    kwargs: Mapping[str, Any],
    merged_extra: Mapping[str, Any],
) -> Optional[Dict[str, Any]]:
    explicit = kwargs.get("thinking") or merged_extra.get("thinking")
    if isinstance(explicit, Mapping):
        return copy.deepcopy(dict(explicit))
    raw_effort = kwargs.get("reasoning_effort") or merged_extra.get("reasoning_effort")
    if raw_effort is None:
        return None
    effort = str(raw_effort).strip().lower()
    if effort in _REASONING_EFFORT_BUDGETS:
        return {"type": "enabled", "budget_tokens": _REASONING_EFFORT_BUDGETS[effort]}
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
                        if msg_cache and "cache_control" not in converted:
                            converted["cache_control"] = dict(msg_cache)
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
            blocks: List[Dict[str, Any]] = []
            raw_content = msg.get("content")

            # Preserve exact ordering when assistant carries ordered provider_blocks
            # (either in content as LLMToolAdapter sends, or in provider_blocks/thinking_blocks).
            if isinstance(raw_content, list):
                has_thinking_in_content = any(
                    isinstance(p, Mapping) and p.get("type") in {"thinking", "redacted_thinking"}
                    for p in raw_content
                )
                if not has_thinking_in_content:
                    for source_key in ("provider_blocks", "thinking_blocks"):
                        raw_pblocks = msg.get(source_key)
                        if isinstance(raw_pblocks, list):
                            for pb in raw_pblocks:
                                if isinstance(pb, Mapping) and pb.get("type") in {"thinking", "redacted_thinking"}:
                                    blocks.append(copy.deepcopy(dict(pb)))
                            if blocks:
                                break
                for part in raw_content:
                    converted = _convert_part_to_anthropic(part)
                    if converted is not None:
                        blocks.append(converted)
            else:
                # Reconstruct ordered blocks from provider_blocks / thinking_blocks + string content.
                added_text_from_provider_blocks = False
                raw_pblocks = msg.get("provider_blocks")
                if isinstance(raw_pblocks, list) and raw_pblocks:
                    for pb in raw_pblocks:
                        converted = _convert_part_to_anthropic(pb)
                        if converted is not None:
                            if converted.get("type") == "text":
                                added_text_from_provider_blocks = True
                            blocks.append(converted)
                else:
                    raw_tblocks = msg.get("thinking_blocks")
                    if isinstance(raw_tblocks, list):
                        for tb in raw_tblocks:
                            if isinstance(tb, Mapping) and tb.get("type") in {"thinking", "redacted_thinking"}:
                                blocks.append(copy.deepcopy(dict(tb)))

                if isinstance(raw_content, str) and raw_content and not added_text_from_provider_blocks:
                    blocks.append({"type": "text", "text": raw_content})

            existing_tool_ids = {
                str(b.get("id") or "")
                for b in blocks
                if b.get("type") == "tool_use" and b.get("id")
            }
            for tc in msg.get("tool_calls") or []:
                if not isinstance(tc, Mapping):
                    continue
                tc_id = str(tc.get("id") or f"toolu_{uuid.uuid4().hex[:12]}")
                if tc_id in existing_tool_ids:
                    continue
                fn = tc.get("function") or {}
                fn_name = str(fn.get("name") or "") if isinstance(fn, Mapping) else ""
                raw_args = fn.get("arguments") if isinstance(fn, Mapping) else {}
                blocks.append(
                    {
                        "type": "tool_use",
                        "id": tc_id,
                        "name": fn_name,
                        "input": extract_tool_arguments_dict(raw_args),
                    }
                )
                existing_tool_ids.add(tc_id)

            _append_alternating_turn(turns, role="assistant", blocks=blocks)
            continue

        # User turn: drop empty text blocks.
        user_blocks: List[Dict[str, Any]] = []
        raw_content = msg.get("content")
        if isinstance(raw_content, str):
            if raw_content:
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

    # Anthropic requires conversations to start with a user turn.
    if not turns or turns[0]["role"] != "user":
        turns.insert(0, {"role": "user", "content": [{"type": "text", "text": "Continue."}]})

    max_tokens = int(
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

    thinking_cfg = _resolve_thinking_config(kwargs, merged_extra)
    thinking_enabled = (
        isinstance(thinking_cfg, Mapping)
        and str(thinking_cfg.get("type") or "").lower() == "enabled"
    )
    if thinking_enabled and isinstance(thinking_cfg, Mapping):
        budget = thinking_cfg.get("budget_tokens")
        if isinstance(budget, int) and max_tokens <= budget:
            prev_max = max_tokens
            max_tokens = budget + 1024
            logger.info(
                "[Anthropic] Adjusted max_tokens from %s to %s to satisfy thinking budget_tokens=%s",
                prev_max,
                max_tokens,
                budget,
            )

    body: Dict[str, Any] = {
        "model": wire_model,
        "messages": turns,
        "max_tokens": max_tokens,
        "stream": bool(stream),
    }

    if system_blocks:
        if has_system_structured:
            body["system"] = system_blocks
        else:
            body["system"] = "\n\n".join(str(b.get("text") or "") for b in system_blocks if b.get("text"))

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
    caller_disable_parallel = False
    if anthropic_tools:
        body["tools"] = anthropic_tools
        converted_choice = _convert_anthropic_tool_choice(kwargs.get("tool_choice"))
        if converted_choice is not None:
            body["tool_choice"] = converted_choice
        if kwargs.get("parallel_tool_calls") is not None:
            raw_ptc = kwargs["parallel_tool_calls"]
            if isinstance(raw_ptc, str):
                raw_ptc = resolve_env_reference(raw_ptc)
            allow_parallel = parse_strict_bool(
                raw_ptc,
                field_name="parallel_tool_calls",
                provider="anthropic",
            )
            if allow_parallel is False:
                caller_disable_parallel = True

    if isinstance(thinking_cfg, Mapping):
        body["thinking"] = dict(thinking_cfg)

    for key, value in merged_extra.items():
        if value is not None and key not in {"thinking", "reasoning_effort"} and not str(key).startswith("_dsa_"):
            body[key] = copy.deepcopy(value)

    # P2: Keep caller parallel_tool_calls=False authoritative AFTER extra_body merge.
    if anthropic_tools and caller_disable_parallel:
        existing_tc = body.get("tool_choice")
        if existing_tc is None:
            body["tool_choice"] = {"type": "auto", "disable_parallel_tool_use": True}
        elif isinstance(existing_tc, Mapping) and str(existing_tc.get("type") or "").lower() != "none":
            updated_tc = dict(existing_tc)
            updated_tc["disable_parallel_tool_use"] = True
            body["tool_choice"] = updated_tc

    # P1-17 & P1-10: Translate supported structured-output format (deep-merging into any
    # existing output_config such as {"effort": "low"}) or fail explicitly instead of
    # silently dropping response_format.
    disable_resp_fmt = bool(kwargs.get("_dsa_disable_response_format"))
    resp_fmt = None if disable_resp_fmt else kwargs.get("response_format")
    if isinstance(resp_fmt, Mapping):
        rtype = str(resp_fmt.get("type") or "").strip().lower()
        if rtype == "json_schema":
            json_schema = resp_fmt.get("json_schema")
            schema_obj = json_schema.get("schema") if isinstance(json_schema, Mapping) else None
            if not isinstance(schema_obj, Mapping):
                raise NativeBadRequestError(
                    "Anthropic response_format type='json_schema' requires a json_schema.schema object",
                    status_code=400,
                    provider="anthropic",
                    error_code="invalid_response_format",
                )
            existing_oc = body.get("output_config")
            if isinstance(existing_oc, Mapping):
                merged_oc = copy.deepcopy(dict(existing_oc))
                if "format" not in merged_oc:
                    merged_oc["format"] = {
                        "type": "json_schema",
                        "schema": copy.deepcopy(dict(schema_obj)),
                    }
                body["output_config"] = merged_oc
            else:
                body["output_config"] = {
                    "format": {
                        "type": "json_schema",
                        "schema": copy.deepcopy(dict(schema_obj)),
                    }
                }
        elif rtype and rtype != "text":
            raise NativeBadRequestError(
                f"Anthropic Messages API does not support response_format type={rtype!r}; "
                "use response_format type='json_schema' with an explicit JSON schema",
                status_code=400,
                provider="anthropic",
                error_code="unsupported_response_format",
            )

    # P2: Post-merge validation for Anthropic extended-thinking constraints
    # (temperature != 1.0, top_p outside [0.95, 1.0], or forced tool_choice 'any'/'tool').
    if thinking_enabled:
        if "temperature" in body and body["temperature"] is not None:
            try:
                merged_temp = float(body["temperature"])
            except (TypeError, ValueError) as exc:
                raise NativeBadRequestError(
                    f"Invalid temperature for Anthropic extended thinking: {body['temperature']!r}",
                    status_code=400,
                    provider="anthropic",
                    error_code="invalid_thinking_params",
                ) from exc
            if merged_temp != 1.0:
                raise NativeBadRequestError(
                    "Anthropic extended thinking requires temperature=1.0 (or omitted)",
                    status_code=400,
                    provider="anthropic",
                    error_code="invalid_thinking_params",
                )
        if "top_p" in body and body["top_p"] is not None:
            try:
                merged_top_p = float(body["top_p"])
            except (TypeError, ValueError) as exc:
                raise NativeBadRequestError(
                    f"Invalid top_p for Anthropic extended thinking: {body['top_p']!r}",
                    status_code=400,
                    provider="anthropic",
                    error_code="invalid_thinking_params",
                ) from exc
            if not (0.95 <= merged_top_p <= 1.0):
                raise NativeBadRequestError(
                    "Anthropic extended thinking requires top_p in [0.95, 1.0] (or omitted)",
                    status_code=400,
                    provider="anthropic",
                    error_code="invalid_thinking_params",
                )
        final_choice = body.get("tool_choice")
        if isinstance(final_choice, Mapping):
            choice_type = str(final_choice.get("type") or "").strip().lower()
            if choice_type in {"any", "tool"}:
                raise NativeBadRequestError(
                    f"Anthropic extended thinking cannot be combined with forced tool_choice type={choice_type!r}",
                    status_code=400,
                    provider="anthropic",
                    error_code="invalid_thinking_params",
                )

    return body


def parse_anthropic_response(
    payload: Mapping[str, Any],
    *,
    default_model: str = "",
    provider: str = "anthropic",
    secrets: Iterable[str] = (),
) -> NativeCompletionResponse:
    """Normalize an Anthropic ``/v1/messages`` JSON payload into :class:`NativeCompletionResponse`.

    Returns ordered ``provider_blocks`` (preserving BOTH ``thinking``/``redacted_thinking``
    and visible ``text`` blocks) when extended thinking is present so 2-turn
    ``LLMToolAdapter`` replay preserves visible text alongside thinking blocks
    without duplicating blocks. Joins text blocks with ``""``.
    """
    check_in_band_json_error(payload, provider=provider, secrets=secrets)

    text_parts: List[str] = []
    reasoning_parts: List[str] = []
    ordered_blocks: List[Dict[str, Any]] = []
    has_thinking = False
    tool_calls: List[NativeToolCall] = []

    for block in payload.get("content") or []:
        if not isinstance(block, Mapping):
            continue
        btype = str(block.get("type") or "")
        if btype == "text":
            if block.get("text") is not None:
                text_val = str(block["text"])
                text_parts.append(text_val)
                if text_val:
                    ordered_blocks.append({"type": "text", "text": text_val})
        elif btype == "thinking":
            has_thinking = True
            ordered_blocks.append(copy.deepcopy(dict(block)))
            if block.get("thinking"):
                reasoning_parts.append(str(block["thinking"]))
        elif btype == "redacted_thinking":
            has_thinking = True
            ordered_blocks.append(copy.deepcopy(dict(block)))
        elif btype == "tool_use":
            idx = len(tool_calls)
            tc_id = str(block.get("id") or f"toolu_{idx}")
            fn_name = str(block.get("name") or "")
            raw_input = block.get("input")
            input_dict = extract_tool_arguments_dict(raw_input)
            args_str = raw_input if isinstance(raw_input, str) else json.dumps(raw_input or {}, ensure_ascii=False)
            # P1-16: Retain tool_use in exact wire order inside ordered_blocks so
            # [thinking, tool_use, text] or [tool_use, text] replays verbatim.
            tool_block: Dict[str, Any] = {
                "type": "tool_use",
                "id": tc_id,
                "name": fn_name,
                "input": input_dict,
            }
            if isinstance(block.get("cache_control"), Mapping):
                tool_block["cache_control"] = dict(block["cache_control"])
            ordered_blocks.append(tool_block)
            tool_calls.append(
                NativeToolCall(
                    id=tc_id,
                    index=idx,
                    function=NativeFunctionCall(
                        name=fn_name,
                        arguments=args_str,
                    ),
                )
            )

    finish_reason = _map_anthropic_stop_reason(
        payload.get("stop_reason"),
        has_tool_calls=bool(tool_calls),
    )
    has_interleaved_tool_and_text = bool(tool_calls) and bool(text_parts)
    preserve_ordered_blocks = has_thinking or has_interleaved_tool_and_text
    message = NativeMessage(
        role=str(payload.get("role") or "assistant"),
        content="".join(text_parts) if text_parts else None,
        tool_calls=tool_calls or None,
        reasoning_content="\n".join(reasoning_parts) if reasoning_parts else None,
        provider_blocks=ordered_blocks if preserve_ordered_blocks else None,
        thinking_blocks=None,
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
    secrets: Iterable[str] = (),
    cancel_check: Optional[Callable[[], None]] = None,
) -> Iterator[NativeStreamChunk]:
    """Stream Anthropic Messages SSE events into normalized :class:`NativeStreamChunk` frames."""
    msg_id = f"msg_{uuid.uuid4().hex[:12]}"
    model_name = default_model
    block_idx_to_tool_idx: Dict[int, int] = {}
    block_accum: Dict[int, Dict[str, Any]] = {}
    saw_tool_calls = False
    emitted_finish = False
    saw_message_stop = False
    raw_usage_state: Dict[str, Any] = {}

    for event_name, data in iter_sse_json_events(
        byte_chunks,
        stop_on_done=False,
        provider=provider,
        secrets=secrets,
        cancel_check=cancel_check,
    ):
        etype = str(data.get("type") or event_name or "")

        if etype == "error" or data.get("error"):
            err_payload: Mapping[str, Any] = data if data.get("error") else {"error": data}
            check_in_band_json_error(err_payload, provider=provider, secrets=secrets)
            raise NativeAPIError(
                f"Anthropic stream error: {err_payload}",
                provider=provider,
                body=err_payload,
                secrets=secrets,
            )

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
                tc_id = str(block.get("id") or f"toolu_{tc_idx}")
                fn_name = str(block.get("name") or "")
                raw_input = block.get("input")
                initial_args = json.dumps(raw_input, ensure_ascii=False) if raw_input else ""
                # P1-9: Accumulate tool_use block alongside thinking/text by index to preserve wire order.
                block_accum[block_idx] = {
                    "type": "tool_use",
                    "id": tc_id,
                    "name": fn_name,
                    "_initial_input": copy.deepcopy(raw_input) if isinstance(raw_input, Mapping) else {},
                    "_json_chunks": [],
                }
                yield NativeStreamChunk(
                    id=msg_id,
                    model=model_name,
                    choices=[
                        NativeChoice(
                            index=0,
                            delta=NativeMessage(
                                tool_calls=[
                                    NativeToolCall(
                                        id=tc_id,
                                        index=tc_idx,
                                        function=NativeFunctionCall(
                                            name=fn_name,
                                            arguments=initial_args,
                                        ),
                                    )
                                ]
                            ),
                        )
                    ],
                )
            elif btype == "text":
                block_accum[block_idx] = {
                    "type": "text",
                    "text": str(block.get("text") or ""),
                }
            elif btype == "thinking":
                block_accum[block_idx] = {
                    "type": "thinking",
                    "thinking": str(block.get("thinking") or ""),
                    "signature": str(block.get("signature") or ""),
                }
            elif btype == "redacted_thinking":
                block_accum[block_idx] = copy.deepcopy(dict(block))
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
                    acc = block_accum.setdefault(block_idx, {"type": "text", "text": ""})
                    if acc.get("type") == "text":
                        acc["text"] += str(text_delta)
                    yield NativeStreamChunk(
                        id=msg_id,
                        model=model_name,
                        choices=[NativeChoice(index=0, delta=NativeMessage(content=str(text_delta)))],
                    )
            elif dtype == "thinking_delta":
                t_delta = delta.get("thinking")
                if t_delta:
                    if block_idx in block_accum and block_accum[block_idx].get("type") == "thinking":
                        block_accum[block_idx]["thinking"] += str(t_delta)
                    yield NativeStreamChunk(
                        id=msg_id,
                        model=model_name,
                        choices=[NativeChoice(index=0, delta=NativeMessage(reasoning_content=str(t_delta)))],
                    )
            elif dtype == "signature_delta":
                sig = delta.get("signature")
                if sig and block_idx in block_accum and block_accum[block_idx].get("type") == "thinking":
                    block_accum[block_idx]["signature"] += str(sig)
            elif dtype == "input_json_delta":
                partial_json = str(delta.get("partial_json") or "")
                if partial_json:
                    tc_idx = block_idx_to_tool_idx.setdefault(block_idx, len(block_idx_to_tool_idx))
                    saw_tool_calls = True
                    if block_idx in block_accum and block_accum[block_idx].get("type") == "tool_use":
                        block_accum[block_idx]["_json_chunks"].append(partial_json)
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
            raw_acc = block_accum.pop(block_idx, None)
            if raw_acc is not None:
                acc_type = raw_acc.get("type")
                final_block: Optional[Dict[str, Any]] = None
                if acc_type == "tool_use":
                    joined_json = "".join(raw_acc.get("_json_chunks") or [])
                    input_obj = (
                        extract_tool_arguments_dict(joined_json)
                        if joined_json
                        else dict(raw_acc.get("_initial_input") or {})
                    )
                    final_block = {
                        "type": "tool_use",
                        "id": raw_acc["id"],
                        "name": raw_acc["name"],
                        "input": input_obj,
                    }
                elif acc_type == "text":
                    if raw_acc.get("text"):
                        final_block = {"type": "text", "text": raw_acc["text"]}
                else:
                    final_block = dict(raw_acc)
                if final_block is not None:
                    yield NativeStreamChunk(
                        id=msg_id,
                        model=model_name,
                        choices=[
                            NativeChoice(
                                index=0,
                                delta=NativeMessage(
                                    provider_blocks=[final_block],
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
            saw_message_stop = True
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
            return

    if not saw_message_stop:
        raise NativeIncompleteStreamError(
            "Anthropic SSE stream ended without message_stop terminal event",
            provider=provider,
            secrets=secrets,
            error_code="incomplete_stream",
        )


def prepare_anthropic_request(
    entry: DeploymentSpec,
    messages: List[Dict[str, Any]],
    stream: bool,
    kwargs: Mapping[str, Any],
    *,
    default_timeout: float = 120.0,
) -> PreparedRequest:
    """Build URL, headers (``x-api-key`` + ``anthropic-version``), JSON body, and timeout."""
    url = entry.endpoint_url or resolve_anthropic_endpoint_url(entry.api_base)
    headers: Dict[str, str] = {
        "Content-Type": "application/json",
        "anthropic-version": ANTHROPIC_DEFAULT_VERSION,
    }
    skip_sensitive = bool(kwargs.get("_dsa_skip_sensitive_caller_headers"))
    merge_header_overrides(headers, {"extra_headers": entry.extra_headers})
    merge_header_overrides(
        headers,
        kwargs,
        resolve_env_fn=resolve_env_reference,
        safe_allowlist_only=skip_sensitive,
    )

    api_key = entry.api_key or (None if skip_sensitive else kwargs.get("api_key"))
    if (
        api_key
        and not has_header_case_insensitive(headers, "x-api-key")
        and not has_header_case_insensitive(headers, "authorization")
    ):
        headers["x-api-key"] = str(api_key)

    effective_kwargs = _merge_request_defaults(entry, kwargs)
    payload = build_anthropic_payload(
        wire_model=entry.wire_model,
        messages=messages,
        stream=stream,
        deployment_extra_body=entry.extra_body,
        **effective_kwargs,
    )
    req_timeout = kwargs.get("timeout")
    if req_timeout is None:
        req_timeout = entry.timeout if entry.timeout is not None else default_timeout
    return url, headers, payload, req_timeout
