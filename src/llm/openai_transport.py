# -*- coding: utf-8 -*-
"""Native HTTPX OpenAI Dual-Protocol Adapter (Chat Completions + Responses API).

Pure prepare/parse/stream-iterator adapter for ``openai_chat`` and
``openai_responses`` wire protocols. Contains zero router/pool orchestration.
"""

from __future__ import annotations

import copy
import json
import re
import time
from typing import Any, Callable, Dict, Iterable, Iterator, List, Mapping, Optional
import uuid

from src.llm.native_resolve import (
    is_official_openai_url,
    resolve_env_reference,
    resolve_openai_endpoint_url,
)
from src.llm.native_types import (
    DeploymentSpec,
    NativeAPIError,
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
    has_header_case_insensitive,
    merge_header_overrides,
    parse_strict_bool,
)
from src.llm.sse import SSEStreamState, iter_sse_json_events

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
    "prompt_cache_key",
    "prompt_cache_retention",
    "store",
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
        "api_surface",
        "dsa_channel_protocol",
        "timeout",
        "num_retries",
        "fallbacks",
        "metadata",
        "caching",
        "drop_params",
        "client",
        "_dsa_deadline_monotonic",
        "_dsa_skip_sensitive_caller_headers",
    }
)

_INTERNAL_MESSAGE_KEYS = frozenset(
    {
        "provider_specific_fields",
        "thinking_blocks",
        "provider_blocks",
        "trace_provider",
        "trace_model",
        "_trace_provider",
        "_trace_model",
        "_dsa_trace_provider",
        "_dsa_trace_model",
    }
)


def _uses_max_completion_tokens(wire_model: str) -> bool:
    """Return True for OpenAI reasoning / GPT-5+ model families requiring ``max_completion_tokens``."""
    parts = [p for p in re.split(r"[/:\s]+", str(wire_model or "").lower()) if p]
    for part in parts:
        if (
            part in {"o1", "o3", "o4"}
            or part.startswith(("o1-", "o3-", "o4-"))
            or part == "gpt-5"
            or part.startswith(("gpt-5-", "gpt-5.", "gpt5", "gpt-6", "gpt6"))
        ):
            return True
    return False


def _extract_caller_kwargs(kwargs: Mapping[str, Any]) -> Dict[str, Any]:
    """Return caller request kwargs without filtered transport metadata keys."""
    return {
        k: v
        for k, v in kwargs.items()
        if k not in _FILTERED_REQUEST_KWARGS
    }


def _merge_request_defaults(
    entry: DeploymentSpec,
    kwargs: Mapping[str, Any],
) -> Dict[str, Any]:
    """Merge R8 deployment defaults under explicit per-request kwargs."""
    merged: Dict[str, Any] = {}
    if isinstance(entry.request_defaults, Mapping):
        for k, v in entry.request_defaults.items():
            if v is not None:
                merged[k] = copy.deepcopy(v)
    for k, v in kwargs.items():
        if k in _FILTERED_REQUEST_KWARGS:
            continue
        if v is None and k == "response_format":
            merged.pop("response_format", None)
            continue
        if v is not None:
            merged[k] = v
    if kwargs.get("_dsa_disable_response_format"):
        merged.pop("response_format", None)
    return merged


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


def _extract_tool_call_thought_sig_and_psf(
    raw_tc: Mapping[str, Any],
) -> tuple[Optional[str], Dict[str, Any]]:
    """Extract ``thought_signature`` and ``provider_specific_fields`` including ``extra_content.google``."""
    psf: Dict[str, Any] = {}
    raw_psf = raw_tc.get("provider_specific_fields")
    if isinstance(raw_psf, Mapping):
        psf.update(dict(raw_psf))
    fn = raw_tc.get("function")
    if isinstance(fn, Mapping) and isinstance(fn.get("provider_specific_fields"), Mapping):
        psf.update(dict(fn["provider_specific_fields"]))

    extra_content = raw_tc.get("extra_content")
    google_sig: Optional[str] = None
    if isinstance(extra_content, Mapping):
        google_obj = extra_content.get("google")
        if isinstance(google_obj, Mapping):
            raw_sig = google_obj.get("thought_signature") or google_obj.get("thoughtSignature")
            if raw_sig:
                google_sig = str(raw_sig)

    sig_val = (
        raw_tc.get("thought_signature")
        or raw_tc.get("thoughtSignature")
        or psf.get("thought_signature")
        or psf.get("thoughtSignature")
        or google_sig
    )
    sig_str = str(sig_val) if sig_val else None
    if sig_str:
        psf.setdefault("thought_signature", sig_str)
    if isinstance(extra_content, Mapping):
        psf.setdefault("extra_content", copy.deepcopy(dict(extra_content)))
    return sig_str, psf


def _sanitize_chat_messages(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Strip internal trace/provider fields from wire Chat messages while keeping ``reasoning_content``."""
    sanitized: List[Dict[str, Any]] = []
    for msg in messages:
        if not isinstance(msg, Mapping):
            continue
        cleaned: Dict[str, Any] = {}
        for k, v in msg.items():
            key_str = str(k)
            if key_str in _INTERNAL_MESSAGE_KEYS or key_str.startswith(("_dsa_", "_trace_")):
                continue
            if key_str == "tool_calls" and isinstance(v, list):
                cleaned_tcs: List[Dict[str, Any]] = []
                for tc in v:
                    if not isinstance(tc, Mapping):
                        continue
                    tc_out: Dict[str, Any] = {}
                    for tk, tv in tc.items():
                        tk_str = str(tk)
                        if (
                            tk_str in _INTERNAL_MESSAGE_KEYS
                            or tk_str == "thought_signature"
                            or tk_str.startswith(("_dsa_", "_trace_"))
                        ):
                            continue
                        if tk_str == "function" and isinstance(tv, Mapping):
                            tc_out["function"] = {
                                fk: fv
                                for fk, fv in tv.items()
                                if str(fk) not in _INTERNAL_MESSAGE_KEYS
                                and not str(fk).startswith(("_dsa_", "_trace_"))
                            }
                        else:
                            tc_out[tk_str] = copy.deepcopy(tv)
                    # Preserve Gemini OpenAI-compat extra_content.google.thought_signature if carried in psf.
                    raw_psf = tc.get("provider_specific_fields")
                    if "extra_content" not in tc_out and isinstance(raw_psf, Mapping):
                        if isinstance(raw_psf.get("extra_content"), Mapping):
                            tc_out["extra_content"] = copy.deepcopy(dict(raw_psf["extra_content"]))
                    cleaned_tcs.append(tc_out)
                cleaned["tool_calls"] = cleaned_tcs
            else:
                cleaned[key_str] = copy.deepcopy(v)
        sanitized.append(cleaned)
    return sanitized


# ============================================================
# Chat Completions Request / Response Translation
# ============================================================


def build_chat_completions_payload(
    *,
    wire_model: str,
    messages: List[Dict[str, Any]],
    stream: bool = False,
    deployment_extra_body: Optional[Mapping[str, Any]] = None,
    deployment_request_defaults: Optional[Mapping[str, Any]] = None,
    endpoint_url: str = "",
    **kwargs: Any,
) -> Dict[str, Any]:
    """Assemble an OpenAI Chat Completions JSON request body."""
    force_max_tokens = bool(kwargs.get("_dsa_force_max_tokens"))
    disable_stream_options = bool(kwargs.get("_dsa_disable_stream_options"))
    disable_response_format = bool(kwargs.get("_dsa_disable_response_format")) or (
        "response_format" in kwargs and kwargs.get("response_format") is None
    )

    body: Dict[str, Any] = {
        "model": wire_model,
        "messages": _sanitize_chat_messages(messages),
        "stream": bool(stream),
    }

    # 1. Apply deployment extra_body (filtering reserved _dsa_* keys, P1-6a).
    if isinstance(deployment_extra_body, Mapping):
        for key, value in deployment_extra_body.items():
            if value is not None and not str(key).startswith("_dsa_"):
                body[key] = copy.deepcopy(value)

    # 2. Apply deployment request_defaults on top of deployment_extra_body (P0-3/P0-4).
    if isinstance(deployment_request_defaults, Mapping):
        for key in _CHAT_COMPLETIONS_OPTIONAL_KEYS:
            if key in deployment_request_defaults and deployment_request_defaults[key] is not None:
                body[key] = copy.deepcopy(deployment_request_defaults[key])
        if (
            stream
            and not disable_stream_options
            and isinstance(deployment_request_defaults.get("stream_options"), Mapping)
        ):
            body["stream_options"] = dict(deployment_request_defaults["stream_options"])

    # 3. Apply explicit caller kwargs on top so caller choices win over deployment defaults.
    caller_extra = kwargs.get("extra_body") if isinstance(kwargs.get("extra_body"), Mapping) else {}
    caller_has_max_tokens = (
        ("max_tokens" in kwargs and kwargs.get("max_tokens") is not None)
        or ("max_tokens" in caller_extra and caller_extra.get("max_tokens") is not None)
    )
    caller_has_max_completion = (
        ("max_completion_tokens" in kwargs and kwargs.get("max_completion_tokens") is not None)
        or ("max_completion_tokens" in caller_extra and caller_extra.get("max_completion_tokens") is not None)
    )

    if stream and not disable_stream_options:
        caller_stream_opts = kwargs.get("stream_options")
        if isinstance(caller_stream_opts, Mapping):
            body["stream_options"] = dict(caller_stream_opts)
        elif (
            caller_stream_opts is None
            and "stream_options" not in body
            and is_official_openai_url(endpoint_url)
        ):
            body["stream_options"] = {"include_usage": True}

    for key in _CHAT_COMPLETIONS_OPTIONAL_KEYS:
        if key in kwargs and kwargs[key] is not None:
            body[key] = kwargs[key]

    if caller_extra:
        for key, value in caller_extra.items():
            if value is not None and not str(key).startswith("_dsa_"):
                body[key] = copy.deepcopy(value)

    # Keep explicit top-level caller store/parallel_tool_calls authoritative over extra_body.
    for auth_key in ("store", "parallel_tool_calls"):
        if kwargs.get(auth_key) is not None:
            body[auth_key] = kwargs[auth_key]

    if disable_stream_options:
        body.pop("stream_options", None)
    if disable_response_format:
        body.pop("response_format", None)

    for bool_key in ("store", "parallel_tool_calls"):
        if bool_key in body and body[bool_key] is not None:
            raw_b = resolve_env_reference(body[bool_key]) if isinstance(body[bool_key], str) else body[bool_key]
            body[bool_key] = parse_strict_bool(raw_b, field_name=bool_key, provider="openai")

    # P1-8: Normalize max_tokens vs max_completion_tokens AFTER all merges so BOTH are never sent.
    if "max_tokens" in body and "max_completion_tokens" in body:
        if caller_has_max_tokens and not caller_has_max_completion:
            body.pop("max_completion_tokens", None)
        else:
            body.pop("max_tokens", None)

    # Map max_tokens -> max_completion_tokens for o1/o3/o4/gpt-5+ families unless
    # one-shot 400 recovery forced max_tokens (P1-10).
    if force_max_tokens:
        if "max_completion_tokens" in body and "max_tokens" not in body:
            body["max_tokens"] = body.pop("max_completion_tokens")
        else:
            body.pop("max_completion_tokens", None)
    elif (
        "max_tokens" in body
        and "max_completion_tokens" not in body
        and _uses_max_completion_tokens(wire_model)
    ):
        body["max_completion_tokens"] = body.pop("max_tokens")

    return body


def parse_chat_completion_response(
    payload: Mapping[str, Any],
    *,
    default_model: str = "",
    provider: str = "openai",
    secrets: Iterable[str] = (),
) -> NativeCompletionResponse:
    """Normalize a Chat Completions JSON payload into :class:`NativeCompletionResponse`."""
    check_in_band_json_error(payload, provider=provider, secrets=secrets)

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
                sig_str, psf = _extract_tool_call_thought_sig_and_psf(raw_tc)
                tool_calls.append(
                    NativeToolCall(
                        id=str(raw_tc.get("id") or f"call_{tc_idx}"),
                        type=str(raw_tc.get("type") or "function"),
                        index=int(raw_tc.get("index", tc_idx)),
                        function=NativeFunctionCall(
                            name=fn.get("name") if isinstance(fn, Mapping) else None,
                            arguments=fn.get("arguments") if isinstance(fn, Mapping) else None,
                        ),
                        thought_signature=sig_str,
                        provider_specific_fields=psf,
                    )
                )

        reasoning = (
            msg_raw.get("reasoning_content") or msg_raw.get("reasoning")
            if isinstance(msg_raw, Mapping)
            else None
        )
        raw_msg_blocks = msg_raw.get("content_blocks") if isinstance(msg_raw, Mapping) else None
        msg_content_blocks = (
            [dict(b) if isinstance(b, Mapping) else b for b in raw_msg_blocks]
            if isinstance(raw_msg_blocks, list)
            else None
        )
        raw_choice_blocks = raw_choice.get("content_blocks")
        choice_content_blocks = (
            [dict(b) if isinstance(b, Mapping) else b for b in raw_choice_blocks]
            if isinstance(raw_choice_blocks, list)
            else None
        )
        msg = NativeMessage(
            role=str(msg_raw.get("role") or "assistant") if isinstance(msg_raw, Mapping) else "assistant",
            content=msg_raw.get("content") if isinstance(msg_raw, Mapping) else None,
            tool_calls=tool_calls,
            reasoning_content=reasoning,
            content_blocks=msg_content_blocks,
        )
        choices.append(
            NativeChoice(
                index=int(raw_choice.get("index", idx)),
                message=msg,
                finish_reason=raw_choice.get("finish_reason"),
                content_blocks=choice_content_blocks,
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
    provider: str = "openai",
    secrets: Iterable[str] = (),
) -> Optional[NativeStreamChunk]:
    """Normalize a single Chat Completions SSE JSON chunk into :class:`NativeStreamChunk`."""
    check_in_band_json_error(payload, provider=provider, secrets=secrets)

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
                sig_str, psf = _extract_tool_call_thought_sig_and_psf(raw_tc)
                tool_calls.append(
                    NativeToolCall(
                        id=raw_tc.get("id"),
                        type=str(raw_tc.get("type") or "function"),
                        index=int(raw_tc.get("index", tc_idx)),
                        function=NativeFunctionCall(
                            name=fn.get("name") if isinstance(fn, Mapping) else None,
                            arguments=fn.get("arguments") if isinstance(fn, Mapping) else None,
                        ),
                        thought_signature=sig_str,
                        provider_specific_fields=psf,
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


def _iter_chat_stream_chunks(
    byte_chunks: Iterable[bytes],
    *,
    default_model: str = "",
    provider: str = "openai",
    secrets: Iterable[str] = (),
    cancel_check: Optional[Callable[[], None]] = None,
) -> Iterator[NativeStreamChunk]:
    """Stream OpenAI Chat Completions SSE chunks, requiring ``[DONE]`` terminal marker."""
    state = SSEStreamState()
    for _ev, data in iter_sse_json_events(
        byte_chunks,
        state=state,
        stop_on_done=True,
        provider=provider,
        secrets=secrets,
        cancel_check=cancel_check,
    ):
        chunk = parse_chat_completion_stream_chunk(
            data,
            default_model=default_model,
            provider=provider,
            secrets=secrets,
        )
        if chunk is not None:
            yield chunk

    if not state.saw_done:
        raise NativeIncompleteStreamError(
            "OpenAI Chat SSE stream ended without [DONE] terminal marker",
            provider=provider,
            secrets=secrets,
            error_code="incomplete_stream",
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
        if ptype in {"reasoning", "thinking", "redacted_thinking"}:
            # Reasoning items are replayed as top-level input items, not message content parts.
            continue
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


def _convert_tool_choice_for_responses(tool_choice: Any) -> Any:
    if tool_choice is None or isinstance(tool_choice, str):
        return tool_choice
    if isinstance(tool_choice, Mapping):
        if tool_choice.get("type") == "function" and isinstance(tool_choice.get("function"), Mapping):
            fn_name = tool_choice["function"].get("name")
            if fn_name:
                return {"type": "function", "name": str(fn_name)}
        return dict(tool_choice)
    return tool_choice


def _convert_response_format_for_responses(response_format: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(response_format, Mapping):
        return None
    rtype = str(response_format.get("type") or "").strip().lower()
    if rtype == "json_object":
        return {"format": {"type": "json_object"}}
    if rtype == "json_schema" and isinstance(response_format.get("json_schema"), Mapping):
        js = response_format["json_schema"]
        fmt: Dict[str, Any] = {"type": "json_schema"}
        if js.get("name") is not None:
            fmt["name"] = str(js["name"])
        if isinstance(js.get("schema"), Mapping):
            fmt["schema"] = dict(js["schema"])
        if js.get("strict") is not None:
            fmt["strict"] = bool(js["strict"])
        return {"format": fmt}
    return None


def _extract_responses_reasoning_items(msg: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """Collect encrypted reasoning items from ``provider_blocks`` or list ``content`` for stateless replay."""
    items: List[Dict[str, Any]] = []
    seen_ids: set[str] = set()

    def _collect(source: Any) -> None:
        if not isinstance(source, list):
            return
        for blk in source:
            if not isinstance(blk, Mapping) or blk.get("type") != "reasoning":
                continue
            item_id = str(blk.get("id") or "")
            if item_id and item_id in seen_ids:
                continue
            if item_id:
                seen_ids.add(item_id)
            replayed: Dict[str, Any] = {"type": "reasoning"}
            if item_id:
                replayed["id"] = item_id
            if isinstance(blk.get("summary"), list):
                replayed["summary"] = copy.deepcopy(blk["summary"])
            else:
                replayed["summary"] = []
            if blk.get("encrypted_content") is not None:
                replayed["encrypted_content"] = blk["encrypted_content"]
            items.append(replayed)

    _collect(msg.get("provider_blocks"))
    _collect(msg.get("content"))
    return items


def build_responses_api_payload(
    *,
    wire_model: str,
    messages: List[Dict[str, Any]],
    stream: bool = False,
    deployment_extra_body: Optional[Mapping[str, Any]] = None,
    deployment_request_defaults: Optional[Mapping[str, Any]] = None,
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
            # P1-9: Preserve interleaved [reasoning_1, function_call_1, reasoning_2, function_call_2]
            # ordering when provider_blocks/content carries ordered Responses items.
            raw_pblocks = msg.get("provider_blocks")
            raw_content = msg.get("content")
            ordered_source = (
                raw_pblocks
                if isinstance(raw_pblocks, list) and raw_pblocks
                else (raw_content if isinstance(raw_content, list) else None)
            )
            has_interleaved_ordered = isinstance(ordered_source, list) and any(
                isinstance(b, Mapping) and b.get("type") in {"reasoning", "function_call"}
                for b in ordered_source
            )
            emitted_call_ids: set[str] = set()
            emitted_text_from_blocks = False

            if has_interleaved_ordered and ordered_source is not None:
                pending_text_parts: List[Dict[str, Any]] = []

                def _flush_pending_text() -> None:
                    nonlocal pending_text_parts
                    if pending_text_parts:
                        input_items.append({"role": "assistant", "content": pending_text_parts})
                        pending_text_parts = []

                for blk in ordered_source:
                    if not isinstance(blk, Mapping):
                        continue
                    btype = str(blk.get("type") or "")
                    if btype == "reasoning":
                        _flush_pending_text()
                        r_item: Dict[str, Any] = {"type": "reasoning"}
                        if blk.get("id"):
                            r_item["id"] = blk["id"]
                        if blk.get("summary") is not None:
                            r_item["summary"] = copy.deepcopy(blk["summary"])
                        else:
                            r_item["summary"] = []
                        if blk.get("encrypted_content") is not None:
                            r_item["encrypted_content"] = blk["encrypted_content"]
                        input_items.append(r_item)
                    elif btype == "function_call":
                        _flush_pending_text()
                        cid = str(blk.get("call_id") or blk.get("id") or f"call_{uuid.uuid4().hex[:8]}")
                        args = blk.get("arguments")
                        if not isinstance(args, str):
                            args = json.dumps(args or {}, ensure_ascii=False)
                        input_items.append(
                            {
                                "type": "function_call",
                                "call_id": cid,
                                "name": str(blk.get("name") or ""),
                                "arguments": args,
                            }
                        )
                        emitted_call_ids.add(cid)
                    elif btype in {"text", "output_text"} and blk.get("text"):
                        emitted_text_from_blocks = True
                        pending_text_parts.append({"type": "output_text", "text": str(blk["text"])})
                _flush_pending_text()
                if not emitted_text_from_blocks and isinstance(raw_content, str) and raw_content:
                    input_items.append(
                        {
                            "role": "assistant",
                            "content": _convert_content_parts_for_responses(raw_content, role="assistant"),
                        }
                    )
            else:
                for reasoning_item in _extract_responses_reasoning_items(msg):
                    input_items.append(reasoning_item)
                converted_content = (
                    _convert_content_parts_for_responses(raw_content, role="assistant")
                    if raw_content
                    else None
                )
                if converted_content:
                    input_items.append(
                        {
                            "role": "assistant",
                            "content": converted_content,
                        }
                    )

            for tc in msg.get("tool_calls") or []:
                if not isinstance(tc, Mapping):
                    continue
                cid = str(tc.get("id") or f"call_{uuid.uuid4().hex[:8]}")
                if cid in emitted_call_ids:
                    continue
                fn = tc.get("function") or {}
                args = fn.get("arguments") if isinstance(fn, Mapping) else ""
                if not isinstance(args, str):
                    args = json.dumps(args or {}, ensure_ascii=False)
                input_items.append(
                    {
                        "type": "function_call",
                        "call_id": cid,
                        "name": str(fn.get("name") or "") if isinstance(fn, Mapping) else "",
                        "arguments": args,
                    }
                )
                emitted_call_ids.add(cid)
            continue

        input_items.append(
            {
                "role": "user",
                "content": _convert_content_parts_for_responses(msg.get("content", ""), role="user"),
            }
        )

    dep_defaults = deployment_request_defaults if isinstance(deployment_request_defaults, Mapping) else {}
    dep_extra = deployment_extra_body if isinstance(deployment_extra_body, Mapping) else {}
    caller_extra = kwargs.get("extra_body") if isinstance(kwargs.get("extra_body"), Mapping) else {}
    merged_extra: Dict[str, Any] = {}
    for k, v in dep_extra.items():
        if v is not None and not str(k).startswith("_dsa_"):
            merged_extra[k] = copy.deepcopy(v)
    for k, v in caller_extra.items():
        if v is not None and not str(k).startswith("_dsa_"):
            merged_extra[k] = copy.deepcopy(v)

    def _pick_param(name: str, default: Any = None) -> Any:
        if kwargs.get(name) is not None:
            return kwargs[name]
        if dep_defaults.get(name) is not None:
            return dep_defaults[name]
        return default

    # P0-4: Resolve store while caller vs deployment sources remain distinct:
    # caller top-level > caller extra_body > deployment request_defaults > deployment extra_body > False.
    if kwargs.get("store") is not None:
        raw_store = kwargs["store"]
    elif "store" in caller_extra and caller_extra["store"] is not None:
        raw_store = caller_extra["store"]
    elif dep_defaults.get("store") is not None:
        raw_store = dep_defaults["store"]
    elif dep_extra.get("store") is not None:
        raw_store = dep_extra["store"]
    else:
        raw_store = False
    if isinstance(raw_store, str):
        raw_store = resolve_env_reference(raw_store)
    store_value = parse_strict_bool(raw_store, field_name="store", provider="openai")

    # P2: Resolve parallel_tool_calls with the same caller-authoritative precedence.
    raw_ptc: Any = None
    if kwargs.get("parallel_tool_calls") is not None:
        raw_ptc = kwargs["parallel_tool_calls"]
    elif "parallel_tool_calls" in caller_extra and caller_extra["parallel_tool_calls"] is not None:
        raw_ptc = caller_extra["parallel_tool_calls"]
    elif dep_defaults.get("parallel_tool_calls") is not None:
        raw_ptc = dep_defaults["parallel_tool_calls"]
    elif dep_extra.get("parallel_tool_calls") is not None:
        raw_ptc = dep_extra["parallel_tool_calls"]

    body: Dict[str, Any] = {
        "model": wire_model,
        "input": input_items,
        "stream": bool(stream),
        "store": store_value,
    }
    if instructions_parts:
        body["instructions"] = "\n\n".join(instructions_parts)

    responses_tools = _convert_tools_for_responses(_pick_param("tools"))
    if responses_tools:
        body["tools"] = responses_tools
    if _pick_param("tool_choice") is not None:
        body["tool_choice"] = _convert_tool_choice_for_responses(_pick_param("tool_choice"))
    if raw_ptc is not None:
        if isinstance(raw_ptc, str):
            raw_ptc = resolve_env_reference(raw_ptc)
        body["parallel_tool_calls"] = parse_strict_bool(
            raw_ptc, field_name="parallel_tool_calls", provider="openai"
        )
    if _pick_param("temperature") is not None:
        body["temperature"] = _pick_param("temperature")
    if _pick_param("top_p") is not None:
        body["top_p"] = _pick_param("top_p")

    max_out = (
        kwargs.get("max_output_tokens")
        or kwargs.get("max_completion_tokens")
        or kwargs.get("max_tokens")
        or dep_defaults.get("max_output_tokens")
        or dep_defaults.get("max_completion_tokens")
        or dep_defaults.get("max_tokens")
    )
    if max_out is not None:
        body["max_output_tokens"] = max_out

    if _pick_param("reasoning_effort") is not None:
        body["reasoning"] = {"effort": _pick_param("reasoning_effort")}

    disable_resp_fmt = bool(kwargs.get("_dsa_disable_response_format")) or (
        "response_format" in kwargs and kwargs.get("response_format") is None
    )
    if isinstance(kwargs.get("text"), Mapping):
        body["text"] = dict(kwargs["text"])
    elif not disable_resp_fmt and "text" not in merged_extra and _pick_param("response_format") is not None:
        converted_text = _convert_response_format_for_responses(_pick_param("response_format"))
        if converted_text is not None:
            body["text"] = converted_text

    for cache_key_field in ("prompt_cache_key", "prompt_cache_retention"):
        val = _pick_param(cache_key_field)
        if val is not None:
            body[cache_key_field] = val

    for key, value in merged_extra.items():
        if value is not None and key not in {"store", "parallel_tool_calls"} and not str(key).startswith("_dsa_"):
            body[key] = value

    # When store=False, request encrypted reasoning content for stateless replay.
    if store_value is False:
        existing_include = body.get("include")
        include_list = list(existing_include) if isinstance(existing_include, list) else []
        if "reasoning.encrypted_content" not in include_list:
            include_list.append("reasoning.encrypted_content")
        body["include"] = include_list

    return body


def parse_responses_api_response(
    payload: Mapping[str, Any],
    *,
    default_model: str = "",
    provider: str = "openai",
    secrets: Iterable[str] = (),
) -> NativeCompletionResponse:
    """Normalize an OpenAI Responses API JSON payload into :class:`NativeCompletionResponse`."""
    check_in_band_json_error(payload, provider=provider, secrets=secrets)

    status = str(payload.get("status") or "").strip().lower()
    if status == "failed":
        err = payload.get("error") or payload
        raise NativeAPIError(
            f"Responses API failed: {err}",
            provider=provider,
            body=payload,
            secrets=secrets,
        )

    text_parts: List[str] = []
    reasoning_parts: List[str] = []
    provider_blocks: List[Dict[str, Any]] = []
    tool_calls: List[NativeToolCall] = []

    for item in payload.get("output") or []:
        if not isinstance(item, Mapping):
            continue
        itype = str(item.get("type") or "")
        if itype == "message":
            for part in item.get("content") or []:
                if not isinstance(part, Mapping):
                    continue
                ptype = str(part.get("type") or "")
                if ptype in {"output_text", "text"} and part.get("text"):
                    text_val = str(part["text"])
                    text_parts.append(text_val)
                    provider_blocks.append({"type": "text", "text": text_val})
                elif ptype == "refusal" and part.get("refusal"):
                    refusal_val = str(part["refusal"])
                    text_parts.append(refusal_val)
                    provider_blocks.append({"type": "text", "text": refusal_val})
        elif itype == "function_call":
            idx = len(tool_calls)
            call_id = str(item.get("call_id") or item.get("id") or f"call_{idx}")
            fn_name = str(item.get("name") or "")
            args = item.get("arguments")
            args_str = args if isinstance(args, str) else json.dumps(args or {}, ensure_ascii=False)
            provider_blocks.append(
                {
                    "type": "function_call",
                    "call_id": call_id,
                    "name": fn_name,
                    "arguments": args_str,
                }
            )
            tool_calls.append(
                NativeToolCall(
                    id=call_id,
                    index=idx,
                    function=NativeFunctionCall(
                        name=fn_name,
                        arguments=args_str,
                    ),
                )
            )
        elif itype == "reasoning":
            reasoning_block: Dict[str, Any] = {"type": "reasoning"}
            if item.get("id"):
                reasoning_block["id"] = item["id"]
            if isinstance(item.get("summary"), list):
                reasoning_block["summary"] = copy.deepcopy(item["summary"])
                for summary_item in item["summary"]:
                    if isinstance(summary_item, Mapping) and summary_item.get("text"):
                        reasoning_parts.append(str(summary_item["text"]))
            if item.get("encrypted_content") is not None:
                reasoning_block["encrypted_content"] = item["encrypted_content"]
            provider_blocks.append(reasoning_block)

    if not text_parts and isinstance(payload.get("output_text"), str) and payload.get("output_text"):
        text_parts.append(payload["output_text"])

    if status == "incomplete":
        finish_reason = "length"
    elif tool_calls:
        finish_reason = "tool_calls"
    else:
        finish_reason = "stop"

    has_reasoning = any(
        blk.get("type") == "reasoning"
        for blk in provider_blocks
    )
    message = NativeMessage(
        role="assistant",
        content="".join(text_parts) if text_parts else None,
        tool_calls=tool_calls or None,
        reasoning_content="\n".join(reasoning_parts) if reasoning_parts else None,
        provider_blocks=provider_blocks if has_reasoning else None,
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
    secrets: Iterable[str] = (),
    cancel_check: Optional[Callable[[], None]] = None,
) -> Iterator[NativeStreamChunk]:
    """Stream Responses API SSE frames as Chat Completions-compatible :class:`NativeStreamChunk`."""
    tool_index_by_key: Dict[str, int] = {}
    emitted_reasoning_ids: set[str] = set()
    pending_reasoning_blocks: Dict[str, Dict[str, Any]] = {}
    saw_tool_calls = False
    saw_terminal = False
    response_id = f"resp-{uuid.uuid4().hex[:12]}"
    model_name = default_model

    def _build_reasoning_block(item: Mapping[str, Any]) -> Dict[str, Any]:
        block: Dict[str, Any] = {"type": "reasoning"}
        if item.get("id"):
            block["id"] = item["id"]
        if isinstance(item.get("summary"), list):
            block["summary"] = copy.deepcopy(item["summary"])
        if item.get("encrypted_content") is not None:
            block["encrypted_content"] = item["encrypted_content"]
        return block

    def _collect_unemitted_reasoning(resp_mapping: Optional[Mapping[str, Any]]) -> List[Dict[str, Any]]:
        # F7: Emit canonical reasoning items in wire order without duplicating IDs whose
        # ciphertext arrived on response.completed instead of response.output_item.done.
        missing: List[Dict[str, Any]] = []
        if isinstance(resp_mapping, Mapping):
            for out_idx, out_item in enumerate(resp_mapping.get("output") or []):
                if not isinstance(out_item, Mapping) or out_item.get("type") != "reasoning":
                    continue
                rkey = str(out_item.get("id") or f"idx:{out_idx}")
                if rkey in emitted_reasoning_ids:
                    continue
                emitted_reasoning_ids.add(rkey)
                prior = pending_reasoning_blocks.pop(rkey, None)
                block = _build_reasoning_block(out_item)
                if prior and block.get("encrypted_content") is None and prior.get("encrypted_content") is not None:
                    block["encrypted_content"] = prior["encrypted_content"]
                missing.append(block)
        for rkey, pending_block in list(pending_reasoning_blocks.items()):
            if rkey not in emitted_reasoning_ids:
                emitted_reasoning_ids.add(rkey)
                missing.append(pending_block)
        pending_reasoning_blocks.clear()
        return missing

    for event_name, data in iter_sse_json_events(
        byte_chunks,
        stop_on_done=True,
        provider=provider,
        secrets=secrets,
        cancel_check=cancel_check,
    ):
        etype = str(data.get("type") or event_name or "")
        resp_obj = data.get("response") if isinstance(data.get("response"), Mapping) else None
        if resp_obj:
            response_id = str(resp_obj.get("id") or response_id)
            model_name = str(resp_obj.get("model") or model_name)

        if etype in {"error", "response.failed"} or data.get("error"):
            err_payload: Mapping[str, Any] = (
                {"error": (resp_obj or {}).get("error") or data.get("error") or data}
            )
            check_in_band_json_error(err_payload, provider=provider, secrets=secrets)
            raise NativeAPIError(
                f"Responses stream error: {err_payload}",
                provider=provider,
                body=err_payload,
                secrets=secrets,
            )

        if etype == "response.output_text.delta":
            delta_text = data.get("delta")
            if delta_text:
                yield NativeStreamChunk(
                    id=response_id,
                    model=model_name,
                    choices=[NativeChoice(index=0, delta=NativeMessage(content=str(delta_text)))],
                )
        elif etype == "response.refusal.delta":
            delta_refusal = data.get("delta")
            if delta_refusal:
                yield NativeStreamChunk(
                    id=response_id,
                    model=model_name,
                    choices=[NativeChoice(index=0, delta=NativeMessage(content=str(delta_refusal)))],
                )
        elif etype in {
            "response.reasoning_summary_text.delta",
            "response.reasoning_text.delta",
            "response.reasoning.delta",
        }:
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
        elif etype == "response.output_item.done":
            # F7 & P1-15: Emit reasoning immediately only when encrypted_content is already present
            # and no earlier reasoning item is buffered awaiting completion ciphertext; otherwise defer
            # to response.completed/incomplete so wire order is preserved with zero duplicate IDs.
            item = data.get("item")
            if isinstance(item, Mapping) and item.get("type") == "reasoning":
                rkey = str(
                    item.get("id")
                    or f"idx:{data.get('output_index', len(emitted_reasoning_ids) + len(pending_reasoning_blocks))}"
                )
                rblock = _build_reasoning_block(item)
                has_cipher = item.get("encrypted_content") is not None
                if rkey not in emitted_reasoning_ids:
                    if has_cipher and not pending_reasoning_blocks:
                        emitted_reasoning_ids.add(rkey)
                        yield NativeStreamChunk(
                            id=response_id,
                            model=model_name,
                            choices=[NativeChoice(index=0, delta=NativeMessage(provider_blocks=[rblock]))],
                        )
                    else:
                        pending_reasoning_blocks[rkey] = rblock
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
        elif etype == "response.incomplete":
            saw_terminal = True
            missing_reasoning = _collect_unemitted_reasoning(resp_obj)
            usage = _normalize_usage((resp_obj or {}).get("usage") or data.get("usage"))
            yield NativeStreamChunk(
                id=response_id,
                model=model_name,
                choices=[
                    NativeChoice(
                        index=0,
                        delta=NativeMessage(provider_blocks=missing_reasoning or None),
                        finish_reason="length",
                    )
                ],
                usage=usage,
            )
            return
        elif etype == "response.completed":
            saw_terminal = True
            missing_reasoning = _collect_unemitted_reasoning(resp_obj)
            usage = _normalize_usage((resp_obj or {}).get("usage") or data.get("usage"))
            resp_status = str((resp_obj or {}).get("status") or "").lower()
            if resp_status == "incomplete":
                finish_reason = "length"
            elif saw_tool_calls:
                finish_reason = "tool_calls"
            else:
                finish_reason = "stop"
            yield NativeStreamChunk(
                id=response_id,
                model=model_name,
                choices=[
                    NativeChoice(
                        index=0,
                        delta=NativeMessage(provider_blocks=missing_reasoning or None),
                        finish_reason=finish_reason,
                    )
                ],
                usage=usage,
            )
            return

    if not saw_terminal:
        raise NativeIncompleteStreamError(
            "OpenAI Responses SSE stream ended without response.completed or response.incomplete event",
            provider=provider,
            secrets=secrets,
            error_code="incomplete_stream",
        )


# ============================================================
# Protocol Adapter Entrypoints (consumed by NativeUnifiedRouter)
# ============================================================


def prepare_openai_request(
    entry: DeploymentSpec,
    messages: List[Dict[str, Any]],
    stream: bool,
    kwargs: Mapping[str, Any],
    *,
    default_timeout: float = 120.0,
) -> PreparedRequest:
    """Build URL, headers, JSON payload, and timeout for OpenAI Chat or Responses protocol."""
    url = entry.endpoint_url or resolve_openai_endpoint_url(
        entry.api_base,
        entry.protocol or "openai_chat",
        provider=entry.provider or "openai",
    )
    headers: Dict[str, str] = {"Content-Type": "application/json"}
    restrict_cross_origin = bool(kwargs.get("_dsa_skip_sensitive_caller_headers"))
    merge_header_overrides(headers, {"extra_headers": entry.extra_headers})
    merge_header_overrides(
        headers,
        kwargs,
        resolve_env_fn=resolve_env_reference,
        safe_allowlist_only=restrict_cross_origin,
    )

    api_key = entry.api_key or (None if restrict_cross_origin else kwargs.get("api_key"))
    if api_key and not has_header_case_insensitive(headers, "authorization"):
        headers["Authorization"] = f"Bearer {api_key}"

    caller_kwargs = _extract_caller_kwargs(kwargs)
    if entry.protocol == "openai_responses":
        payload = build_responses_api_payload(
            wire_model=entry.wire_model,
            messages=messages,
            stream=stream,
            deployment_extra_body=entry.extra_body,
            deployment_request_defaults=entry.request_defaults,
            **caller_kwargs,
        )
    else:
        payload = build_chat_completions_payload(
            wire_model=entry.wire_model,
            messages=messages,
            stream=stream,
            deployment_extra_body=entry.extra_body,
            deployment_request_defaults=entry.request_defaults,
            endpoint_url=url,
            **caller_kwargs,
        )

    req_timeout = kwargs.get("timeout")
    if req_timeout is None:
        req_timeout = entry.timeout if entry.timeout is not None else default_timeout
    return url, headers, payload, req_timeout


def parse_openai_response(
    entry: DeploymentSpec,
    payload: Mapping[str, Any],
    secrets: Iterable[str] = (),
) -> NativeCompletionResponse:
    """Parse OpenAI Chat Completions or Responses JSON response."""
    if entry.protocol == "openai_responses":
        return parse_responses_api_response(
            payload,
            default_model=entry.wire_model,
            provider=entry.provider or "openai",
            secrets=secrets,
        )
    return parse_chat_completion_response(
        payload,
        default_model=entry.wire_model,
        provider=entry.provider or "openai",
        secrets=secrets,
    )


def iter_openai_stream_chunks(
    entry: DeploymentSpec,
    byte_chunks: Iterable[bytes],
    secrets: Iterable[str] = (),
    cancel_check: Optional[Callable[[], None]] = None,
) -> Iterator[NativeStreamChunk]:
    """Iterate normalized stream chunks for OpenAI Chat Completions or Responses SSE."""
    if entry.protocol == "openai_responses":
        return _iter_responses_stream_chunks(
            byte_chunks,
            default_model=entry.wire_model,
            provider=entry.provider or "openai",
            secrets=secrets,
            cancel_check=cancel_check,
        )
    return _iter_chat_stream_chunks(
        byte_chunks,
        default_model=entry.wire_model,
        provider=entry.provider or "openai",
        secrets=secrets,
        cancel_check=cancel_check,
    )
