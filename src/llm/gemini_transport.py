# -*- coding: utf-8 -*-
"""Native HTTPX Google Gemini REST API Adapter.

Pure prepare/parse/stream-iterator adapter for Gemini REST
(``:generateContent`` and ``:streamGenerateContent?alt=sse``) with:
- Query-safe ``/v1beta`` & ``alt=sse`` URL resolution (official and custom proxies)
- ``x-goog-api-key`` header auth (respecting existing ``?key=`` or custom auth overrides)
- Preserved / deterministic ``functionCall.id`` echoed in ``functionResponse``
- ``thoughtSignature`` round-tripping on ANY part (functionCall and text parts)
- Per-candidate streaming tool-call state and mandatory ``finishReason`` verification
- ``promptFeedback.blockReason`` content-filter errors
- Allowlisted ``extra_body``, LiteLLM-parity JSON schema sanitization, ``inlineData``,
  and ``reasoning_effort`` -> ``thinkingConfig`` mapping
"""

from __future__ import annotations

import copy
import hashlib
import json
import time
from typing import Any, Callable, Dict, Iterable, Iterator, List, Mapping, Optional, Set, Tuple
from urllib.parse import parse_qsl, urlsplit
import uuid

from src.llm.native_resolve import resolve_gemini_endpoint_url
from src.llm.native_types import (
    DeploymentSpec,
    NativeBadRequestError,
    NativeChoice,
    NativeCompletionResponse,
    NativeContentFilterError,
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
)
from src.llm.sse import iter_sse_json_events

_GEMINI_ALLOWED_EXTRA_BODY_KEYS: frozenset[str] = frozenset(
    {
        "generationConfig",
        "safetySettings",
        "cachedContent",
        "toolConfig",
    }
)

_GEMINI_UNSUPPORTED_SCHEMA_KEYS: frozenset[str] = frozenset(
    {
        "$schema",
        "$id",
        "$comment",
        "$defs",
        "definitions",
        "additionalProperties",
        "default",
        "title",
        "examples",
        "exclusiveMinimum",
        "exclusiveMaximum",
        "propertyNames",
        "patternProperties",
        "minProperties",
        "maxProperties",
        "strict",
    }
)

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

_GEMINI_REASONING_EFFORT_BUDGETS: Dict[str, int] = {
    "none": 0,
    "off": 0,
    "disabled": 0,
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
        if v is not None:
            merged[k] = v
    return merged


def _resolve_json_pointer(root: Mapping[str, Any], ref: str) -> Optional[Mapping[str, Any]]:
    """Resolve a local JSON pointer such as ``#/$defs/Foo`` or ``#/definitions/Bar``."""
    if not isinstance(ref, str) or not ref.startswith("#/"):
        return None
    current: Any = root
    for segment in ref[2:].split("/"):
        decoded = segment.replace("~1", "/").replace("~0", "~")
        if isinstance(current, Mapping) and decoded in current:
            current = current[decoded]
        else:
            return None
    return current if isinstance(current, Mapping) else None


def _clean_gemini_schema(
    node: Any,
    *,
    root: Optional[Mapping[str, Any]] = None,
    seen_refs: Optional[Set[str]] = None,
) -> Any:
    """Sanitize JSON Schema to Gemini/LiteLLM parity (inline $ref/$defs, nullable type arrays, strip keys)."""
    if root is None and isinstance(node, Mapping):
        root = node
    if seen_refs is None:
        seen_refs = set()

    if isinstance(node, list):
        return [_clean_gemini_schema(item, root=root, seen_refs=seen_refs) for item in node]
    if not isinstance(node, Mapping):
        return node

    # 1. Inline local $ref definitions (with cycle protection).
    ref = node.get("$ref")
    if isinstance(ref, str) and root is not None:
        if ref in seen_refs:
            return {"type": "object"}
        target = _resolve_json_pointer(root, ref)
        if target is not None:
            merged_node = dict(target)
            for k, v in node.items():
                if k != "$ref":
                    merged_node[k] = v
            return _clean_gemini_schema(merged_node, root=root, seen_refs=seen_refs | {ref})

    cleaned: Dict[str, Any] = {}
    nullable_flag = bool(node.get("nullable", False))

    # 2. Collapse anyOf / oneOf with a null branch into a single nullable schema.
    for union_key in ("anyOf", "oneOf"):
        raw_union = node.get(union_key)
        if isinstance(raw_union, list) and raw_union:
            non_null: List[Any] = []
            saw_null = False
            for branch in raw_union:
                if isinstance(branch, Mapping) and str(branch.get("type") or "").lower() == "null":
                    saw_null = True
                else:
                    non_null.append(branch)
            if saw_null and len(non_null) == 1 and isinstance(non_null[0], Mapping):
                merged_branch = dict(non_null[0])
                for k, v in node.items():
                    if k != union_key and k not in merged_branch:
                        merged_branch[k] = v
                merged_branch["nullable"] = True
                return _clean_gemini_schema(merged_branch, root=root, seen_refs=seen_refs)

    for key, value in node.items():
        if key in _GEMINI_UNSUPPORTED_SCHEMA_KEYS or key == "$ref":
            continue
        if key == "type" and isinstance(value, list):
            non_null_types = [str(t) for t in value if str(t).lower() != "null"]
            if len(non_null_types) < len(value):
                nullable_flag = True
            cleaned["type"] = non_null_types[0] if non_null_types else "string"
            continue
        if key == "const":
            cleaned["enum"] = [value]
            continue
        cleaned[key] = _clean_gemini_schema(value, root=root, seen_refs=seen_refs)

    if nullable_flag:
        cleaned["nullable"] = True

    if isinstance(cleaned.get("properties"), Mapping) and isinstance(cleaned.get("required"), list):
        prop_keys = set(cleaned["properties"].keys())
        filtered_req = [r for r in cleaned["required"] if r in prop_keys]
        if filtered_req:
            cleaned["required"] = filtered_req
        else:
            cleaned.pop("required", None)

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


def _check_prompt_feedback_block(
    payload: Mapping[str, Any],
    *,
    provider: str = "gemini",
    secrets: Iterable[str] = (),
) -> None:
    feedback = payload.get("promptFeedback")
    if not isinstance(feedback, Mapping):
        return
    block_reason = str(feedback.get("blockReason") or "").strip()
    if block_reason:
        block_msg = str(feedback.get("blockReasonMessage") or "").strip()
        detail = f"{block_reason}: {block_msg}" if block_msg else block_reason
        raise NativeContentFilterError(
            f"Gemini prompt blocked (blockReason={detail})",
            provider=provider,
            body=payload,
            secrets=secrets,
            error_code="content_filter",
        )


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


def _is_gemini_file_uri(url: str) -> bool:
    lowered = url.lower()
    if lowered.startswith("gs://"):
        return True
    split = urlsplit(url)
    host = (split.hostname or "").lower()
    return host == "generativelanguage.googleapis.com" and "/files/" in (split.path or "").lower()


def _convert_part_to_gemini(part: Any) -> Optional[Dict[str, Any]]:
    if isinstance(part, str):
        return {"text": part} if part else None
    if not isinstance(part, Mapping):
        return None

    # Pass native Gemini inlineData / inline_data parts through directly.
    raw_inline = part.get("inlineData") or part.get("inline_data")
    if isinstance(raw_inline, Mapping):
        mime_type = str(raw_inline.get("mimeType") or raw_inline.get("mime_type") or "").strip()
        b64_data = str(raw_inline.get("data") or "").strip()
        if mime_type and b64_data:
            out_part: Dict[str, Any] = {"inlineData": {"mimeType": mime_type, "data": b64_data}}
            sig = part.get("thoughtSignature") or part.get("thought_signature")
            if sig:
                out_part["thoughtSignature"] = str(sig)
            return out_part
        return None

    if isinstance(part.get("fileData"), Mapping):
        return copy.deepcopy(dict(part))

    ptype = str(part.get("type") or ("text" if "text" in part else "")).strip().lower()
    if ptype in {"text", "input_text", "output_text"}:
        text_val = str(part.get("text") or "")
        if not text_val and not (part.get("thoughtSignature") or part.get("thought_signature")):
            return None
        out_part = {"text": text_val}
        sig = part.get("thoughtSignature") or part.get("thought_signature")
        if sig:
            out_part["thoughtSignature"] = str(sig)
        return out_part

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
        if _is_gemini_file_uri(url_str):
            return {"fileData": {"fileUri": url_str}}
        raise NativeBadRequestError(
            "Gemini REST API does not support arbitrary HTTP(S) image URLs in fileUri; "
            "pass base64 data URLs or inlineData instead",
            status_code=400,
            provider="gemini",
        )
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
            return [copy.deepcopy(dict(t)) for t in tools if isinstance(t, Mapping)]
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
            call_id = str(msg.get("tool_call_id") or "").strip()
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
            fn_resp: Dict[str, Any] = {"name": fn_name, "response": resp_obj}
            if call_id:
                fn_resp["id"] = call_id
            _append_gemini_turn(
                contents,
                role="user",
                parts=[{"functionResponse": fn_resp}],
            )
            continue

        if role == "assistant":
            model_parts: List[Dict[str, Any]] = []
            raw_content = msg.get("content")
            raw_pblocks = msg.get("provider_blocks")
            if isinstance(raw_content, list):
                for item in raw_content:
                    converted = _convert_part_to_gemini(item)
                    if converted is not None:
                        model_parts.append(converted)
            elif isinstance(raw_pblocks, list) and raw_pblocks:
                for item in raw_pblocks:
                    converted = _convert_part_to_gemini(item)
                    if converted is not None:
                        model_parts.append(converted)
                if not model_parts and isinstance(raw_content, str) and raw_content:
                    model_parts.append({"text": raw_content})
            elif isinstance(raw_content, str) and raw_content:
                model_parts.append({"text": raw_content})

            for tc in msg.get("tool_calls") or []:
                if not isinstance(tc, Mapping):
                    continue
                fn = tc.get("function") or {}
                fn_name = str(fn.get("name") or "") if isinstance(fn, Mapping) else ""
                raw_args = fn.get("arguments") if isinstance(fn, Mapping) else {}
                fc_obj: Dict[str, Any] = {
                    "name": fn_name,
                    "args": extract_tool_arguments_dict(raw_args),
                }
                tc_id = str(tc.get("id") or "").strip()
                if tc_id:
                    fc_obj["id"] = tc_id
                fc_part: Dict[str, Any] = {"functionCall": fc_obj}
                psf = tc.get("provider_specific_fields")
                sig = (
                    tc.get("thought_signature")
                    or tc.get("thoughtSignature")
                    or (
                        (psf.get("thought_signature") or psf.get("thoughtSignature"))
                        if isinstance(psf, Mapping)
                        else None
                    )
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
        gen_cfg.update(copy.deepcopy(dict(kwargs["generation_config"])))
    if isinstance(kwargs.get("thinking_config"), Mapping):
        gen_cfg["thinkingConfig"] = copy.deepcopy(dict(kwargs["thinking_config"]))
    elif "thinkingConfig" not in gen_cfg and kwargs.get("reasoning_effort") is not None:
        effort = str(kwargs["reasoning_effort"]).strip().lower()
        if effort in _GEMINI_REASONING_EFFORT_BUDGETS:
            gen_cfg["thinkingConfig"] = {"thinkingBudget": _GEMINI_REASONING_EFFORT_BUDGETS[effort]}

    gemini_tools = _convert_gemini_tools(kwargs.get("tools"))
    if gemini_tools:
        body["tools"] = gemini_tools
        tool_cfg = _convert_gemini_tool_choice(kwargs.get("tool_choice"))
        if tool_cfg is not None:
            body["toolConfig"] = tool_cfg

    # Allowlisted extra_body keys only; deep-merge generationConfig.
    merged_extra: Dict[str, Any] = {}
    if isinstance(deployment_extra_body, Mapping):
        merged_extra.update(deployment_extra_body)
    if isinstance(kwargs.get("extra_body"), Mapping):
        merged_extra.update(kwargs["extra_body"])
    for key, value in merged_extra.items():
        if value is None or key not in _GEMINI_ALLOWED_EXTRA_BODY_KEYS:
            continue
        if key == "generationConfig" and isinstance(value, Mapping):
            gen_cfg.update(copy.deepcopy(dict(value)))
        else:
            body[key] = copy.deepcopy(value)

    if gen_cfg:
        body["generationConfig"] = gen_cfg

    return body


def _deterministic_gemini_call_id(cand_idx: int, tc_idx: int, fn_name: str, args_str: str) -> str:
    digest = hashlib.sha256(f"{cand_idx}:{tc_idx}:{fn_name}:{args_str}".encode("utf-8")).hexdigest()[:10]
    safe_name = fn_name or "fn"
    return f"call_{safe_name}_{tc_idx}_{digest}"


def _extract_gemini_parts(
    parts: Iterable[Any],
    *,
    cand_idx: int = 0,
    tool_index_start: int = 0,
) -> Tuple[List[str], List[str], List[NativeToolCall], List[Dict[str, Any]], bool]:
    text_parts: List[str] = []
    reasoning_parts: List[str] = []
    tool_calls: List[NativeToolCall] = []
    provider_blocks: List[Dict[str, Any]] = []
    has_text_thought_signature = False

    for part in parts:
        if not isinstance(part, Mapping):
            continue
        sig = part.get("thoughtSignature") or part.get("thought_signature")
        sig_str = str(sig) if sig else None

        if "text" in part and part.get("text") is not None:
            text_val = str(part["text"])
            if part.get("thought") is True:
                reasoning_parts.append(text_val)
            else:
                text_parts.append(text_val)
                text_block: Dict[str, Any] = {"type": "text", "text": text_val}
                if sig_str:
                    text_block["thoughtSignature"] = sig_str
                    has_text_thought_signature = True
                provider_blocks.append(text_block)
        elif isinstance(part.get("functionCall"), Mapping):
            fc = part["functionCall"]
            tc_idx = tool_index_start + len(tool_calls)
            fn_name = str(fc.get("name") or "")
            args_str = json.dumps(fc.get("args") or {}, ensure_ascii=False, sort_keys=True)
            raw_id = str(fc.get("id") or "").strip()
            call_id = raw_id or _deterministic_gemini_call_id(cand_idx, tc_idx, fn_name, args_str)
            psf = {"thought_signature": sig_str} if sig_str else {}
            tool_calls.append(
                NativeToolCall(
                    id=call_id,
                    index=tc_idx,
                    function=NativeFunctionCall(
                        name=fn_name,
                        arguments=args_str,
                    ),
                    thought_signature=sig_str,
                    provider_specific_fields=psf,
                )
            )
    return text_parts, reasoning_parts, tool_calls, provider_blocks, has_text_thought_signature


def parse_gemini_response(
    payload: Mapping[str, Any],
    *,
    default_model: str = "",
    provider: str = "gemini",
    secrets: Iterable[str] = (),
) -> NativeCompletionResponse:
    """Normalize a Gemini ``generateContent`` JSON payload into :class:`NativeCompletionResponse`."""
    check_in_band_json_error(payload, provider=provider, secrets=secrets)
    _check_prompt_feedback_block(payload, provider=provider, secrets=secrets)

    choices: List[NativeChoice] = []
    for idx, cand in enumerate(payload.get("candidates") or []):
        if not isinstance(cand, Mapping):
            continue
        cand_idx = int(cand.get("index", idx))
        content_obj = cand.get("content") if isinstance(cand.get("content"), Mapping) else {}
        parts = content_obj.get("parts") or []
        text_parts, reasoning_parts, tool_calls, provider_blocks, has_text_sig = _extract_gemini_parts(
            parts,
            cand_idx=cand_idx,
        )
        finish_reason = _map_gemini_finish_reason(
            cand.get("finishReason"),
            has_tool_calls=bool(tool_calls),
        )
        choices.append(
            NativeChoice(
                index=cand_idx,
                message=NativeMessage(
                    role="assistant",
                    content="".join(text_parts) if text_parts else None,
                    tool_calls=tool_calls or None,
                    reasoning_content="\n".join(reasoning_parts) if reasoning_parts else None,
                    provider_blocks=provider_blocks if has_text_sig else None,
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
    secrets: Iterable[str] = (),
    cancel_check: Optional[Callable[[], None]] = None,
) -> Iterator[NativeStreamChunk]:
    """Stream Gemini ``streamGenerateContent?alt=sse`` frames as :class:`NativeStreamChunk`."""
    tool_count_by_cand: Dict[int, int] = {}
    saw_tools_by_cand: Dict[int, bool] = {}
    saw_finish_reason = False
    response_id = f"gemini-{uuid.uuid4().hex[:12]}"
    model_name = default_model

    for _ev, data in iter_sse_json_events(
        byte_chunks,
        stop_on_done=False,
        provider=provider,
        secrets=secrets,
        cancel_check=cancel_check,
    ):
        check_in_band_json_error(data, provider=provider, secrets=secrets)
        _check_prompt_feedback_block(data, provider=provider, secrets=secrets)

        response_id = str(data.get("responseId") or response_id)
        model_name = str(data.get("modelVersion") or model_name)
        usage = parse_gemini_usage(data.get("usageMetadata"))
        candidates = data.get("candidates") or []

        choices: List[NativeChoice] = []
        for idx, cand in enumerate(candidates):
            if not isinstance(cand, Mapping):
                continue
            cand_idx = int(cand.get("index", idx))
            content_obj = cand.get("content") if isinstance(cand.get("content"), Mapping) else {}
            parts = content_obj.get("parts") or []
            start_idx = tool_count_by_cand.get(cand_idx, 0)
            text_parts, reasoning_parts, tool_calls, provider_blocks, has_text_sig = _extract_gemini_parts(
                parts,
                cand_idx=cand_idx,
                tool_index_start=start_idx,
            )
            if tool_calls:
                tool_count_by_cand[cand_idx] = start_idx + len(tool_calls)
                saw_tools_by_cand[cand_idx] = True

            raw_finish = cand.get("finishReason")
            if raw_finish:
                saw_finish_reason = True
            finish_reason = _map_gemini_finish_reason(
                raw_finish,
                has_tool_calls=saw_tools_by_cand.get(cand_idx, False),
            )
            delta = NativeMessage(
                role="assistant",
                content="".join(text_parts) if text_parts else None,
                tool_calls=tool_calls or None,
                reasoning_content="\n".join(reasoning_parts) if reasoning_parts else None,
                provider_blocks=provider_blocks if has_text_sig else None,
            )
            choices.append(
                NativeChoice(
                    index=cand_idx,
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

    if not saw_finish_reason:
        raise NativeIncompleteStreamError(
            "Gemini SSE stream ended without a terminal finishReason",
            provider=provider,
            secrets=secrets,
            error_code="incomplete_stream",
        )


def prepare_gemini_request(
    entry: DeploymentSpec,
    messages: List[Dict[str, Any]],
    stream: bool,
    kwargs: Mapping[str, Any],
    *,
    default_timeout: float = 120.0,
) -> PreparedRequest:
    """Build Gemini REST URL, ``x-goog-api-key`` headers, JSON body, and timeout."""
    url = resolve_gemini_endpoint_url(entry.api_base, entry.wire_model, stream=stream)
    headers: Dict[str, str] = {"Content-Type": "application/json"}
    merge_header_overrides(headers, {"extra_headers": entry.extra_headers})
    merge_header_overrides(headers, kwargs)

    query_keys = {k.lower() for k, _ in parse_qsl(urlsplit(url).query, keep_blank_values=True)}
    api_key = entry.api_key or kwargs.get("api_key")
    if (
        api_key
        and "key" not in query_keys
        and not has_header_case_insensitive(headers, "x-goog-api-key")
        and not has_header_case_insensitive(headers, "authorization")
    ):
        headers["x-goog-api-key"] = str(api_key)

    effective_kwargs = _merge_request_defaults(entry, kwargs)
    payload = build_gemini_payload(
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
