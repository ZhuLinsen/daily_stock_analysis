# -*- coding: utf-8 -*-
"""
===================================
Native HTTPX Google Gemini REST API Adapter
===================================

Issue #2622 Phase 2b: direct Gemini REST serializer/parser (``generateContent`` &
``streamGenerateContent?alt=sse``), ``x-goog-api-key`` header auth (no URL secret
exposure), Vision ``inlineData``, ``thoughtSignature`` two-way round-tripping on
tool calls, ``functionResponse`` name resolution, ``thought`` part extraction,
and ``usageMetadata`` normalization compatible with ``src/llm/usage.py``.
"""

from __future__ import annotations

import json
import time
from typing import Any, Dict, Iterable, Iterator, List, Mapping, Optional
import uuid

from src.llm.native_types import (
    DEFAULT_GEMINI_BASE,
    NativeAPIError,
    NativeChoice,
    NativeCompletionResponse,
    NativeFunctionCall,
    NativeMessage,
    NativeStreamChunk,
    NativeToolCall,
    NativeUsage,
    PreparedRequest,
    classify_http_error,
    extract_tool_arguments_dict,
    has_header_case_insensitive,
    merge_header_overrides,
    parse_data_url,
)
from src.llm.pool import DeploymentEntry
from src.llm.sse import iter_sse_json_events

_GEMINI_UNSUPPORTED_SCHEMA_KEYS = frozenset({"$schema", "additionalProperties"})

_FINISH_REASON_MAP = {
    "STOP": "stop",
    "MAX_TOKENS": "length",
    "SAFETY": "content_filter",
    "RECITATION": "content_filter",
    "BLOCKLIST": "content_filter",
    "PROHIBITED_CONTENT": "content_filter",
    "SPII": "content_filter",
    "MALFORMED_FUNCTION_CALL": "stop",
}


def resolve_gemini_endpoint(
    api_base: Optional[str],
    wire_model: str,
    *,
    stream: bool = False,
) -> str:
    """Resolve Gemini REST ``:generateContent`` or ``:streamGenerateContent?alt=sse`` URL."""
    base = (api_base or DEFAULT_GEMINI_BASE).strip().rstrip("/")
    if (
        "generativelanguage.googleapis.com" in base.lower()
        and not base.endswith(("/v1beta", "/v1", "/v1alpha"))
        and "/models/" not in base
    ):
        base = f"{base}/v1beta"

    method_suffix = ":streamGenerateContent?alt=sse" if stream else ":generateContent"
    for suffix in (":streamGenerateContent?alt=sse", ":streamGenerateContent", ":generateContent"):
        if base.endswith(suffix):
            return base[: -len(suffix)] + method_suffix

    clean_model = wire_model.strip().lstrip("/")
    if not clean_model.startswith("models/"):
        clean_model = f"models/{clean_model}"
    return f"{base}/{clean_model}{method_suffix}"


def _clean_gemini_schema(node: Any) -> Any:
    if isinstance(node, list):
        return [_clean_gemini_schema(item) for item in node]
    if not isinstance(node, Mapping):
        return node
    cleaned: Dict[str, Any] = {}
    for key, value in node.items():
        if key in _GEMINI_UNSUPPORTED_SCHEMA_KEYS:
            continue
        cleaned[key] = _clean_gemini_schema(value)
    return cleaned


def _map_gemini_finish_reason(
    finish_reason: Optional[str],
    *,
    has_tool_calls: bool = False,
) -> Optional[str]:
    if finish_reason is None:
        return "tool_calls" if has_tool_calls else None
    key = str(finish_reason).strip().upper()
    if key == "STOP" and has_tool_calls:
        return "tool_calls"
    mapped = _FINISH_REASON_MAP.get(key)
    if mapped is not None:
        return mapped
    return "tool_calls" if has_tool_calls else "stop"


def parse_gemini_usage(raw_usage: Any) -> Optional[NativeUsage]:
    """Normalize Gemini ``usageMetadata`` compatible with ``src/llm/usage.py``."""
    if not isinstance(raw_usage, Mapping):
        return None
    prompt_tokens = raw_usage.get("promptTokenCount")
    candidates_tokens = raw_usage.get("candidatesTokenCount")
    total_tokens = raw_usage.get("totalTokenCount")
    cached_tokens = raw_usage.get("cachedContentTokenCount")
    thoughts_tokens = raw_usage.get("thoughtsTokenCount")

    if total_tokens is None and prompt_tokens is not None and candidates_tokens is not None:
        total_tokens = int(prompt_tokens) + int(candidates_tokens) + (
            int(thoughts_tokens) if thoughts_tokens is not None else 0
        )

    prompt_details: Optional[Dict[str, Any]] = None
    if cached_tokens is not None:
        prompt_details = {"cached_tokens": int(cached_tokens)}

    completion_details: Optional[Dict[str, Any]] = None
    if thoughts_tokens is not None:
        completion_details = {"reasoning_tokens": int(thoughts_tokens)}

    extra: Dict[str, Any] = {}
    if cached_tokens is not None:
        extra["cached_content_token_count"] = int(cached_tokens)

    return NativeUsage(
        prompt_tokens=int(prompt_tokens) if prompt_tokens is not None else None,
        completion_tokens=int(candidates_tokens) if candidates_tokens is not None else None,
        total_tokens=int(total_tokens) if total_tokens is not None else None,
        prompt_tokens_details=prompt_details,
        completion_tokens_details=completion_details,
        extra=extra,
    )


def _convert_part_to_gemini(part: Any) -> Optional[Dict[str, Any]]:
    if isinstance(part, str):
        return {"text": part} if part else None
    if not isinstance(part, Mapping):
        return None
    ptype = str(part.get("type") or "text").strip().lower()
    if ptype in {"text", "input_text", "output_text"}:
        return {"text": str(part.get("text") or "")}
    if ptype == "image_url":
        img = part.get("image_url")
        url = img.get("url") if isinstance(img, Mapping) else img
        url_str = str(url or "").strip()
        if not url_str:
            return None
        parsed_data = parse_data_url(url_str)
        if parsed_data is not None:
            mime_type, b64_data = parsed_data
            return {"inlineData": {"mimeType": mime_type, "data": b64_data}}
        return {"fileData": {"fileUri": url_str}}
    return None


def _append_gemini_turn(
    contents: List[Dict[str, Any]],
    *,
    role: str,
    parts: List[Dict[str, Any]],
) -> None:
    if not parts:
        return
    if contents and contents[-1]["role"] == role:
        contents[-1]["parts"].extend(parts)
        return
    contents.append({"role": role, "parts": parts})


def _convert_gemini_tools(tools: Any) -> Optional[List[Dict[str, Any]]]:
    if not isinstance(tools, list) or not tools:
        return None
    declarations: List[Dict[str, Any]] = []
    for tool in tools:
        if not isinstance(tool, Mapping):
            continue
        if tool.get("type") == "function" and isinstance(tool.get("function"), Mapping):
            fn = tool["function"]
            decl: Dict[str, Any] = {
                "name": str(fn.get("name") or ""),
                "description": str(fn.get("description") or ""),
            }
            if isinstance(fn.get("parameters"), Mapping):
                decl["parameters"] = _clean_gemini_schema(fn["parameters"])
            declarations.append(decl)
        elif "functionDeclarations" in tool:
            return [dict(t) for t in tools if isinstance(t, Mapping)]
    if not declarations:
        return None
    return [{"functionDeclarations": declarations}]


def _convert_gemini_tool_choice(tool_choice: Any) -> Optional[Dict[str, Any]]:
    if tool_choice is None:
        return None
    if isinstance(tool_choice, str):
        choice = tool_choice.strip().lower()
        if choice == "auto":
            return {"functionCallingConfig": {"mode": "AUTO"}}
        if choice in {"required", "any"}:
            return {"functionCallingConfig": {"mode": "ANY"}}
        if choice == "none":
            return {"functionCallingConfig": {"mode": "NONE"}}
        return None
    if isinstance(tool_choice, Mapping):
        if tool_choice.get("type") == "function" and isinstance(tool_choice.get("function"), Mapping):
            fn_name = tool_choice["function"].get("name")
            if fn_name:
                return {
                    "functionCallingConfig": {
                        "mode": "ANY",
                        "allowedFunctionNames": [str(fn_name)],
                    }
                }
        return dict(tool_choice)
    return None


def _collect_tool_names_by_id(messages: List[Dict[str, Any]]) -> Dict[str, str]:
    mapping: Dict[str, str] = {}
    for msg in messages:
        if not isinstance(msg, Mapping):
            continue
        for tc in msg.get("tool_calls") or []:
            if not isinstance(tc, Mapping):
                continue
            call_id = str(tc.get("id") or "")
            fn = tc.get("function") or {}
            fn_name = str(fn.get("name") or "") if isinstance(fn, Mapping) else ""
            if call_id and fn_name:
                mapping[call_id] = fn_name
    return mapping


def build_gemini_payload(
    *,
    wire_model: str,
    messages: List[Dict[str, Any]],
    stream: bool = False,
    deployment_extra_body: Optional[Mapping[str, Any]] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Translate OpenAI Chat-style messages/tools/params into a Gemini REST JSON body."""
    del wire_model, stream  # Gemini encodes model + stream inside endpoint URL.
    system_parts: List[Dict[str, Any]] = []
    contents: List[Dict[str, Any]] = []
    tool_name_by_id = _collect_tool_names_by_id(messages)

    for msg in messages:
        if not isinstance(msg, Mapping):
            continue
        role = str(msg.get("role") or "user").strip().lower()

        if role in {"system", "developer"}:
            raw_sys = msg.get("content")
            if isinstance(raw_sys, str) and raw_sys.strip():
                system_parts.append({"text": raw_sys.strip()})
            elif isinstance(raw_sys, list):
                for item in raw_sys:
                    converted = _convert_part_to_gemini(item)
                    if converted is not None:
                        system_parts.append(converted)
            continue

        if role == "tool":
            call_id = str(msg.get("tool_call_id") or "")
            fn_name = str(msg.get("name") or tool_name_by_id.get(call_id) or "tool")
            raw_out = msg.get("content")
            if isinstance(raw_out, Mapping):
                resp_obj: Dict[str, Any] = dict(raw_out)
            elif isinstance(raw_out, str):
                try:
                    parsed = json.loads(raw_out)
                    resp_obj = parsed if isinstance(parsed, dict) else {"result": parsed}
                except ValueError:
                    resp_obj = {"result": raw_out}
            else:
                resp_obj = {"result": raw_out}
            _append_gemini_turn(
                contents,
                role="user",
                parts=[{"functionResponse": {"name": fn_name, "response": resp_obj}}],
            )
            continue

        if role == "assistant":
            model_parts: List[Dict[str, Any]] = []
            raw_content = msg.get("content")
            if isinstance(raw_content, str) and raw_content:
                model_parts.append({"text": raw_content})
            elif isinstance(raw_content, list):
                for item in raw_content:
                    converted = _convert_part_to_gemini(item)
                    if converted is not None:
                        model_parts.append(converted)

            for tc in msg.get("tool_calls") or []:
                if not isinstance(tc, Mapping):
                    continue
                fn = tc.get("function") or {}
                fn_name = str(fn.get("name") or "") if isinstance(fn, Mapping) else ""
                raw_args = fn.get("arguments") if isinstance(fn, Mapping) else {}
                fc_part: Dict[str, Any] = {
                    "functionCall": {
                        "name": fn_name,
                        "args": extract_tool_arguments_dict(raw_args),
                    }
                }
                psf = tc.get("provider_specific_fields")
                sig = tc.get("thought_signature") or (
                    psf.get("thought_signature") if isinstance(psf, Mapping) else None
                )
                if sig:
                    fc_part["thoughtSignature"] = str(sig)
                model_parts.append(fc_part)

            _append_gemini_turn(contents, role="model", parts=model_parts)
            continue

        user_parts: List[Dict[str, Any]] = []
        raw_content = msg.get("content")
        if isinstance(raw_content, str):
            if raw_content:
                user_parts.append({"text": raw_content})
        elif isinstance(raw_content, list):
            for item in raw_content:
                converted = _convert_part_to_gemini(item)
                if converted is not None:
                    user_parts.append(converted)
        _append_gemini_turn(contents, role="user", parts=user_parts)

    body: Dict[str, Any] = {"contents": contents}
    if system_parts:
        body["systemInstruction"] = {"parts": system_parts}

    gen_cfg: Dict[str, Any] = {}
    if kwargs.get("temperature") is not None:
        gen_cfg["temperature"] = kwargs["temperature"]
    if kwargs.get("top_p") is not None:
        gen_cfg["topP"] = kwargs["top_p"]
    if kwargs.get("top_k") is not None:
        gen_cfg["topK"] = kwargs["top_k"]

    max_out = (
        kwargs.get("max_output_tokens")
        or kwargs.get("max_completion_tokens")
        or kwargs.get("max_tokens")
    )
    if max_out is not None:
        gen_cfg["maxOutputTokens"] = int(max_out)

    stop_val = kwargs.get("stop")
    if isinstance(stop_val, str) and stop_val:
        gen_cfg["stopSequences"] = [stop_val]
    elif isinstance(stop_val, list) and stop_val:
        gen_cfg["stopSequences"] = [str(s) for s in stop_val]

    resp_fmt = kwargs.get("response_format")
    if isinstance(resp_fmt, Mapping):
        rtype = str(resp_fmt.get("type") or "").lower()
        if rtype == "json_object":
            gen_cfg["responseMimeType"] = "application/json"
        elif rtype == "json_schema":
            gen_cfg["responseMimeType"] = "application/json"
            json_schema = resp_fmt.get("json_schema")
            schema_obj = json_schema.get("schema") if isinstance(json_schema, Mapping) else None
            if isinstance(schema_obj, Mapping):
                gen_cfg["responseSchema"] = _clean_gemini_schema(schema_obj)

    if isinstance(kwargs.get("generation_config"), Mapping):
        gen_cfg.update(kwargs["generation_config"])
    if isinstance(kwargs.get("thinking_config"), Mapping):
        gen_cfg["thinkingConfig"] = dict(kwargs["thinking_config"])

    if gen_cfg:
        body["generationConfig"] = gen_cfg

    gemini_tools = _convert_gemini_tools(kwargs.get("tools"))
    if gemini_tools:
        body["tools"] = gemini_tools
        tool_cfg = _convert_gemini_tool_choice(kwargs.get("tool_choice"))
        if tool_cfg is not None:
            body["toolConfig"] = tool_cfg

    merged_extra: Dict[str, Any] = {}
    if isinstance(deployment_extra_body, Mapping):
        merged_extra.update(deployment_extra_body)
    if isinstance(kwargs.get("extra_body"), Mapping):
        merged_extra.update(kwargs["extra_body"])
    for key, value in merged_extra.items():
        if value is not None:
            body[key] = value

    return body


def _extract_gemini_parts(
    parts: Iterable[Any],
    *,
    tool_index_start: int = 0,
) -> tuple[List[str], List[str], List[NativeToolCall]]:
    text_parts: List[str] = []
    reasoning_parts: List[str] = []
    tool_calls: List[NativeToolCall] = []

    for part in parts:
        if not isinstance(part, Mapping):
            continue
        if "text" in part and part.get("text") is not None:
            text_val = str(part["text"])
            if part.get("thought") is True:
                reasoning_parts.append(text_val)
            else:
                text_parts.append(text_val)
        elif isinstance(part.get("functionCall"), Mapping):
            fc = part["functionCall"]
            tc_idx = tool_index_start + len(tool_calls)
            args_str = json.dumps(fc.get("args") or {}, ensure_ascii=False)
            sig = part.get("thoughtSignature") or part.get("thought_signature")
            sig_str = str(sig) if sig else None
            psf = {"thought_signature": sig_str} if sig_str else {}
            tool_calls.append(
                NativeToolCall(
                    id=f"call_{uuid.uuid4().hex[:12]}",
                    index=tc_idx,
                    function=NativeFunctionCall(
                        name=str(fc.get("name") or ""),
                        arguments=args_str,
                    ),
                    thought_signature=sig_str,
                    provider_specific_fields=psf,
                )
            )
    return text_parts, reasoning_parts, tool_calls


def parse_gemini_response(
    payload: Mapping[str, Any],
    *,
    default_model: str = "",
) -> NativeCompletionResponse:
    """Normalize a Gemini ``generateContent`` JSON payload into :class:`NativeCompletionResponse`."""
    choices: List[NativeChoice] = []
    for idx, cand in enumerate(payload.get("candidates") or []):
        if not isinstance(cand, Mapping):
            continue
        content_obj = cand.get("content") if isinstance(cand.get("content"), Mapping) else {}
        parts = content_obj.get("parts") or []
        text_parts, reasoning_parts, tool_calls = _extract_gemini_parts(parts)
        finish_reason = _map_gemini_finish_reason(
            cand.get("finishReason"),
            has_tool_calls=bool(tool_calls),
        )
        choices.append(
            NativeChoice(
                index=int(cand.get("index", idx)),
                message=NativeMessage(
                    role="assistant",
                    content="".join(text_parts) if text_parts else None,
                    tool_calls=tool_calls or None,
                    reasoning_content="\n".join(reasoning_parts) if reasoning_parts else None,
                ),
                finish_reason=finish_reason,
            )
        )

    if not choices:
        choices.append(NativeChoice(index=0, message=NativeMessage(role="assistant"), finish_reason="stop"))

    return NativeCompletionResponse(
        id=str(payload.get("responseId") or f"gemini-{uuid.uuid4().hex[:12]}"),
        model=str(payload.get("modelVersion") or default_model),
        choices=choices,
        usage=parse_gemini_usage(payload.get("usageMetadata")),
        created=int(time.time()),
        object="chat.completion",
    )


def iter_gemini_stream_chunks(
    byte_chunks: Iterable[bytes],
    *,
    default_model: str = "",
    provider: str = "gemini",
) -> Iterator[NativeStreamChunk]:
    """Stream Gemini ``streamGenerateContent?alt=sse`` frames as :class:`NativeStreamChunk`."""
    tool_count = 0
    saw_tool_calls = False
    response_id = f"gemini-{uuid.uuid4().hex[:12]}"
    model_name = default_model

    for _ev, data in iter_sse_json_events(byte_chunks):
        if isinstance(data.get("error"), Mapping):
            err_status = int(data["error"].get("code") or 500)
            raise classify_http_error(
                err_status,
                json.dumps(data, ensure_ascii=False),
                provider=provider,
            )

        response_id = str(data.get("responseId") or response_id)
        model_name = str(data.get("modelVersion") or model_name)
        usage = parse_gemini_usage(data.get("usageMetadata"))
        candidates = data.get("candidates") or []

        choices: List[NativeChoice] = []
        for idx, cand in enumerate(candidates):
            if not isinstance(cand, Mapping):
                continue
            content_obj = cand.get("content") if isinstance(cand.get("content"), Mapping) else {}
            parts = content_obj.get("parts") or []
            text_parts, reasoning_parts, tool_calls = _extract_gemini_parts(
                parts,
                tool_index_start=tool_count,
            )
            if tool_calls:
                tool_count += len(tool_calls)
                saw_tool_calls = True
            finish_reason = _map_gemini_finish_reason(
                cand.get("finishReason"),
                has_tool_calls=saw_tool_calls,
            )
            delta = NativeMessage(
                role="assistant",
                content="".join(text_parts) if text_parts else None,
                tool_calls=tool_calls or None,
                reasoning_content="\n".join(reasoning_parts) if reasoning_parts else None,
            )
            choices.append(
                NativeChoice(
                    index=int(cand.get("index", idx)),
                    delta=delta,
                    finish_reason=finish_reason,
                )
            )

        if not choices and usage is not None:
            choices = [NativeChoice(index=0, delta=NativeMessage(), finish_reason=None)]
        if choices or usage is not None:
            yield NativeStreamChunk(
                id=response_id,
                model=model_name,
                choices=choices,
                usage=usage,
            )


def prepare_gemini_request(
    entry: DeploymentEntry,
    messages: List[Dict[str, Any]],
    stream: bool,
    kwargs: Mapping[str, Any],
    *,
    default_timeout: float = 120.0,
) -> PreparedRequest:
    """Build Gemini REST URL, ``x-goog-api-key`` headers, JSON body, and timeout."""
    url = resolve_gemini_endpoint(entry.api_base, entry.wire_model, stream=stream)
    headers: Dict[str, str] = {"Content-Type": "application/json"}
    headers.update(entry.extra_headers)
    merge_header_overrides(headers, kwargs)

    api_key = entry.api_key or kwargs.get("api_key")
    if (
        api_key
        and not has_header_case_insensitive(headers, "x-goog-api-key")
        and not has_header_case_insensitive(headers, "authorization")
    ):
        headers["x-goog-api-key"] = str(api_key)

    filtered_kwargs = {
        k: v
        for k, v in kwargs.items()
        if k not in {"wire_model", "messages", "stream", "deployment_extra_body", "client"}
    }
    payload = build_gemini_payload(
        wire_model=entry.wire_model,
        messages=messages,
        stream=stream,
        deployment_extra_body=entry.extra_body,
        **filtered_kwargs,
    )
    req_timeout = float(kwargs.get("timeout") or entry.timeout or default_timeout)
    return url, headers, payload, req_timeout
