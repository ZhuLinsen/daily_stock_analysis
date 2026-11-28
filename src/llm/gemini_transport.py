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
import logging
import re
import time
from typing import Any, Callable, Dict, Iterable, Iterator, List, Mapping, Optional, Set, Tuple
from urllib.parse import parse_qsl, urlsplit
import uuid

from src.llm.native_resolve import resolve_env_reference, resolve_gemini_endpoint_url
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

logger = logging.getLogger(__name__)

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
    "MALFORMED_FUNCTION_CALL": "malformed_function_call",
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
        if key == "properties" and isinstance(value, Mapping):
            # P1-19: Preserve EVERY user property name verbatim (e.g. 'title', 'default', 'strict')
            # and recurse only on each property's schema value.
            cleaned["properties"] = {
                prop_name: _clean_gemini_schema(prop_schema, root=root, seen_refs=seen_refs)
                for prop_name, prop_schema in value.items()
            }
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


def _normalize_gemini_finish_reason_raw(finish_reason: Optional[str]) -> Optional[str]:
    """Normalize provider finishReason; treat blank or FINISH_REASON_UNSPECIFIED as non-terminal (P1-11b)."""
    if finish_reason is None:
        return None
    key = str(finish_reason).strip().upper()
    if not key or key == "FINISH_REASON_UNSPECIFIED":
        return None
    return key


def _map_gemini_finish_reason(
    finish_reason: Optional[str],
    *,
    has_tool_calls: bool = False,
) -> Optional[str]:
    # P1-20 & P1-11b: Emit finish_reason ONLY when the provider supplied a real terminal finishReason.
    key = _normalize_gemini_finish_reason_raw(finish_reason)
    if key is None:
        return None
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
    tool_use_prompt_tokens = raw_usage.get("toolUsePromptTokenCount")

    # P2: Include thoughtsTokenCount in completion_tokens and toolUsePromptTokenCount in fallback total.
    completion_tokens: Optional[int] = None
    if candidates_tokens is not None or thoughts_tokens is not None:
        completion_tokens = (
            (int(candidates_tokens) if candidates_tokens is not None else 0)
            + (int(thoughts_tokens) if thoughts_tokens is not None else 0)
        )

    if total_tokens is None and prompt_tokens is not None and completion_tokens is not None:
        total_tokens = (
            int(prompt_tokens)
            + (int(tool_use_prompt_tokens) if tool_use_prompt_tokens is not None else 0)
            + completion_tokens
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
    if tool_use_prompt_tokens is not None:
        extra["tool_use_prompt_token_count"] = int(tool_use_prompt_tokens)

    return NativeUsage(
        prompt_tokens=int(prompt_tokens) if prompt_tokens is not None else None,
        completion_tokens=completion_tokens,
        total_tokens=int(total_tokens) if total_tokens is not None else None,
        prompt_tokens_details=prompt_details,
        completion_tokens_details=completion_details,
        extra=extra,
    )


_GEMINI_FILES_API_PATH_RE = re.compile(r"^/(?:v1|v1beta|v1alpha)/files/[^/\s]+$", re.IGNORECASE)


def _is_gemini_file_uri(url: str) -> bool:
    """Validate Gemini Files API or Cloud Storage URI strictly (P2)."""
    raw = str(url or "").strip()
    if not raw:
        return False
    split = urlsplit(raw)
    scheme = (split.scheme or "").lower()
    if scheme == "gs":
        bucket = (split.netloc or "").strip()
        obj_path = (split.path or "").lstrip("/").strip()
        return bool(bucket and obj_path)
    host = (split.hostname or "").lower()
    return (
        scheme == "https"
        and host == "generativelanguage.googleapis.com"
        and bool(_GEMINI_FILES_API_PATH_RE.match(split.path or ""))
    )


def _convert_part_to_gemini(part: Any) -> Optional[Dict[str, Any]]:
    if isinstance(part, str):
        return {"text": part} if part else None
    if not isinstance(part, Mapping):
        return None

    sig = part.get("thoughtSignature") or part.get("thought_signature")
    sig_str = str(sig) if sig else None

    # P1-18: Pass native Gemini functionCall parts through in exact wire order.
    raw_fc = part.get("functionCall")
    if isinstance(raw_fc, Mapping):
        fc_out: Dict[str, Any] = {
            "name": str(raw_fc.get("name") or ""),
            "args": extract_tool_arguments_dict(raw_fc.get("args")),
        }
        if raw_fc.get("id"):
            fc_out["id"] = str(raw_fc["id"])
        out_fc: Dict[str, Any] = {"functionCall": fc_out}
        if sig_str:
            out_fc["thoughtSignature"] = sig_str
        return out_fc

    # Pass native Gemini inlineData / inline_data parts through directly.
    raw_inline = part.get("inlineData") or part.get("inline_data")
    if isinstance(raw_inline, Mapping):
        mime_type = str(raw_inline.get("mimeType") or raw_inline.get("mime_type") or "").strip()
        b64_data = str(raw_inline.get("data") or "").strip()
        if mime_type and b64_data:
            out_part: Dict[str, Any] = {"inlineData": {"mimeType": mime_type, "data": b64_data}}
            if sig_str:
                out_part["thoughtSignature"] = sig_str
            return out_part
        return None

    raw_file_data = part.get("fileData") or part.get("file_data")
    if isinstance(raw_file_data, Mapping):
        file_uri = str(raw_file_data.get("fileUri") or raw_file_data.get("file_uri") or "").strip()
        if not file_uri or not _is_gemini_file_uri(file_uri):
            raise NativeBadRequestError(
                "Gemini REST API fileData.fileUri only accepts gs:// or Gemini Files API URIs; "
                "pass base64 data URLs or inlineData instead",
                status_code=400,
                provider="gemini",
            )
        fd_out: Dict[str, Any] = {"fileUri": file_uri}
        mime_val = raw_file_data.get("mimeType") or raw_file_data.get("mime_type")
        if mime_val:
            fd_out["mimeType"] = str(mime_val)
        out_fd: Dict[str, Any] = {"fileData": fd_out}
        if sig_str:
            out_fd["thoughtSignature"] = sig_str
        return out_fd

    # P1-18: Preserve thought: True text parts with their thoughtSignature.
    if part.get("thought") is True:
        out_thought: Dict[str, Any] = {"thought": True}
        if part.get("text") is not None:
            out_thought["text"] = str(part["text"])
        if sig_str:
            out_thought["thoughtSignature"] = sig_str
        return out_thought

    # P1-18: Preserve signature-only parts carrying thoughtSignature without text/functionCall.
    if sig_str and "text" not in part and not part.get("type"):
        return {"thoughtSignature": sig_str}

    ptype = str(part.get("type") or ("text" if "text" in part else "")).strip().lower()
    if ptype in {"text", "input_text", "output_text"}:
        text_val = str(part.get("text") or "")
        if not text_val and not sig_str:
            return None
        out_part = {"text": text_val} if text_val or "text" in part else {}
        if sig_str:
            out_part["thoughtSignature"] = sig_str
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
    del stream  # Gemini encodes stream mode inside endpoint URL.
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

            # P1-18: Avoid duplicating or reordering functionCalls already preserved in exact
            # wire order inside provider_blocks.
            existing_fc_ids = {
                str(p["functionCall"].get("id") or "")
                for p in model_parts
                if isinstance(p.get("functionCall"), Mapping) and p["functionCall"].get("id")
            }
            existing_fc_count = sum(1 for p in model_parts if isinstance(p.get("functionCall"), Mapping))

            for tc in msg.get("tool_calls") or []:
                if not isinstance(tc, Mapping):
                    continue
                tc_id = str(tc.get("id") or "").strip()
                if tc_id and tc_id in existing_fc_ids:
                    continue
                if not tc_id and existing_fc_count > 0:
                    continue
                fn = tc.get("function") or {}
                fn_name = str(fn.get("name") or "") if isinstance(fn, Mapping) else ""
                raw_args = fn.get("arguments") if isinstance(fn, Mapping) else {}
                fc_obj: Dict[str, Any] = {
                    "name": fn_name,
                    "args": extract_tool_arguments_dict(raw_args),
                }
                if tc_id:
                    fc_obj["id"] = tc_id
                    existing_fc_ids.add(tc_id)
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

    resp_fmt = None if kwargs.get("_dsa_disable_response_format") else kwargs.get("response_format")
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
            budget = _GEMINI_REASONING_EFFORT_BUDGETS[effort]
            # P2: Gemini 2.5 Pro cannot disable thinking (thinkingBudget=0 returns HTTP 400).
            if budget == 0 and "gemini-2.5-pro" in str(wire_model or "").lower():
                logger.warning(
                    "[Gemini] Model %s does not support disabling thinking (reasoning_effort=%r); omitting thinkingBudget=0",
                    wire_model,
                    effort,
                )
            else:
                gen_cfg["thinkingConfig"] = {"thinkingBudget": budget}

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


_MAX_GEMINI_JSONPATH_INDEX = 1024
_JSON_PATH_IDENT_RE = re.compile(r"^[A-Za-z_$][A-Za-z0-9_$-]*")


def _parse_json_path_tokens(path: str) -> List[Any]:
    """Strictly parse a singular Gemini JSONPath (e.g. ``$.rows[0]['target.symbol']``) (P1-11a)."""
    raw = str(path or "").strip()
    if not raw or not raw.startswith("$"):
        raise NativeBadRequestError(
            f"Malformed Gemini partialArgs jsonPath: {path!r}",
            status_code=400,
            provider="gemini",
            error_code="invalid_partial_args_path",
        )
    idx = 1
    n = len(raw)
    tokens: List[Any] = []
    while idx < n:
        ch = raw[idx]
        if ch == ".":
            idx += 1
            if idx >= n:
                raise NativeBadRequestError(
                    f"Malformed Gemini partialArgs jsonPath (trailing dot): {path!r}",
                    status_code=400,
                    provider="gemini",
                    error_code="invalid_partial_args_path",
                )
            match = _JSON_PATH_IDENT_RE.match(raw[idx:])
            if not match:
                raise NativeBadRequestError(
                    f"Malformed Gemini partialArgs jsonPath segment at {idx}: {path!r}",
                    status_code=400,
                    provider="gemini",
                    error_code="invalid_partial_args_path",
                )
            tokens.append(match.group(0))
            idx += match.end()
        elif ch == "[":
            idx += 1
            if idx >= n:
                raise NativeBadRequestError(
                    f"Unterminated bracket in Gemini partialArgs jsonPath: {path!r}",
                    status_code=400,
                    provider="gemini",
                    error_code="invalid_partial_args_path",
                )
            quote_ch = raw[idx]
            if quote_ch in ("'", '"'):
                idx += 1
                chars: List[str] = []
                closed = False
                _simple_escapes = {
                    "b": "\b",
                    "f": "\f",
                    "n": "\n",
                    "r": "\r",
                    "t": "\t",
                    "/": "/",
                    "\\": "\\",
                }
                while idx < n:
                    cur_ch = raw[idx]
                    if cur_ch == "\\":
                        if idx + 1 >= n:
                            raise NativeBadRequestError(
                                f"Unterminated escape in Gemini partialArgs jsonPath: {path!r}",
                                status_code=400,
                                provider="gemini",
                                error_code="invalid_partial_args_path",
                            )
                        esc = raw[idx + 1]
                        if esc == quote_ch:
                            chars.append(quote_ch)
                            idx += 2
                            continue
                        if esc in _simple_escapes:
                            chars.append(_simple_escapes[esc])
                            idx += 2
                            continue
                        if esc == "u":
                            hex4 = raw[idx + 2 : idx + 6]
                            if len(hex4) < 4 or not all(c in "0123456789abcdefABCDEF" for c in hex4):
                                raise NativeBadRequestError(
                                    f"Malformed \\u escape in Gemini partialArgs jsonPath: {path!r}",
                                    status_code=400,
                                    provider="gemini",
                                    error_code="invalid_partial_args_path",
                                )
                            code_unit = int(hex4, 16)
                            idx += 6
                            if 0xD800 <= code_unit <= 0xDBFF:
                                if raw[idx : idx + 2] != "\\u":
                                    raise NativeBadRequestError(
                                        f"Unpaired high surrogate in Gemini partialArgs jsonPath: {path!r}",
                                        status_code=400,
                                        provider="gemini",
                                        error_code="invalid_partial_args_path",
                                    )
                                low_hex = raw[idx + 2 : idx + 6]
                                if len(low_hex) < 4 or not all(c in "0123456789abcdefABCDEF" for c in low_hex):
                                    raise NativeBadRequestError(
                                        f"Malformed surrogate pair in Gemini partialArgs jsonPath: {path!r}",
                                        status_code=400,
                                        provider="gemini",
                                        error_code="invalid_partial_args_path",
                                    )
                                low_unit = int(low_hex, 16)
                                if not (0xDC00 <= low_unit <= 0xDFFF):
                                    raise NativeBadRequestError(
                                        f"Invalid low surrogate in Gemini partialArgs jsonPath: {path!r}",
                                        status_code=400,
                                        provider="gemini",
                                        error_code="invalid_partial_args_path",
                                    )
                                idx += 6
                                combined = 0x10000 + ((code_unit - 0xD800) << 10) + (low_unit - 0xDC00)
                                chars.append(chr(combined))
                            elif 0xDC00 <= code_unit <= 0xDFFF:
                                raise NativeBadRequestError(
                                    f"Unpaired low surrogate in Gemini partialArgs jsonPath: {path!r}",
                                    status_code=400,
                                    provider="gemini",
                                    error_code="invalid_partial_args_path",
                                )
                            else:
                                chars.append(chr(code_unit))
                            continue
                        raise NativeBadRequestError(
                            f"Invalid escape sequence '\\{esc}' in Gemini partialArgs jsonPath: {path!r}",
                            status_code=400,
                            provider="gemini",
                            error_code="invalid_partial_args_path",
                        )
                    if cur_ch == quote_ch:
                        idx += 1
                        closed = True
                        break
                    if 0xD800 <= ord(cur_ch) <= 0xDFFF:
                        raise NativeBadRequestError(
                            f"Unpaired surrogate character in Gemini partialArgs jsonPath: {path!r}",
                            status_code=400,
                            provider="gemini",
                            error_code="invalid_partial_args_path",
                        )
                    chars.append(cur_ch)
                    idx += 1
                if not closed or idx >= n or raw[idx] != "]":
                    raise NativeBadRequestError(
                        f"Malformed quoted bracket key in Gemini partialArgs jsonPath: {path!r}",
                        status_code=400,
                        provider="gemini",
                        error_code="invalid_partial_args_path",
                    )
                tokens.append("".join(chars))
                idx += 1
            else:
                close_pos = raw.find("]", idx)
                if close_pos == -1:
                    raise NativeBadRequestError(
                        f"Unterminated index in Gemini partialArgs jsonPath: {path!r}",
                        status_code=400,
                        provider="gemini",
                        error_code="invalid_partial_args_path",
                    )
                index_text = raw[idx:close_pos]
                if not index_text.isdigit():
                    raise NativeBadRequestError(
                        f"Unsupported non-integer array index in Gemini partialArgs jsonPath: {path!r}",
                        status_code=400,
                        provider="gemini",
                        error_code="invalid_partial_args_path",
                    )
                arr_idx = int(index_text)
                if arr_idx > _MAX_GEMINI_JSONPATH_INDEX:
                    raise NativeBadRequestError(
                        f"Gemini partialArgs jsonPath array index {arr_idx} exceeds limit {_MAX_GEMINI_JSONPATH_INDEX}",
                        status_code=400,
                        provider="gemini",
                        error_code="invalid_partial_args_path",
                    )
                tokens.append(arr_idx)
                idx = close_pos + 1
        else:
            raise NativeBadRequestError(
                f"Malformed Gemini partialArgs jsonPath character {ch!r} at {idx}: {path!r}",
                status_code=400,
                provider="gemini",
                error_code="invalid_partial_args_path",
            )
    if not tokens:
        raise NativeBadRequestError(
            f"Empty Gemini partialArgs jsonPath: {path!r}",
            status_code=400,
            provider="gemini",
            error_code="invalid_partial_args_path",
        )
    return tokens


def _apply_gemini_partial_args(
    target_args: Dict[str, Any],
    partial_args: Iterable[Any],
    pending_leaf_paths: Set[Tuple[Any, ...]],
) -> None:
    """Apply Gemini streaming ``partialArgs`` updates onto ``target_args`` with sparse-array & leaf tracking (P1-11a)."""
    for item in partial_args:
        if not isinstance(item, Mapping):
            continue
        raw_path = item.get("jsonPath")
        if raw_path is None:
            continue
        tokens = _parse_json_path_tokens(str(raw_path))
        path_key = tuple(tokens)

        has_value = True
        if "stringValue" in item:
            val: Any = str(item["stringValue"])
            is_string = True
        elif "numberValue" in item:
            num = item["numberValue"]
            val = int(num) if isinstance(num, float) and num.is_integer() else num
            is_string = False
        elif "boolValue" in item:
            val = bool(item["boolValue"])
            is_string = False
        elif "nullValue" in item:
            val = None
            is_string = False
        else:
            has_value = False
            val = None
            is_string = False

        if item.get("willContinue") is True:
            pending_leaf_paths.add(path_key)
        else:
            pending_leaf_paths.discard(path_key)

        if not has_value:
            continue

        cur: Any = target_args
        for idx, tok in enumerate(tokens[:-1]):
            nxt = tokens[idx + 1]
            expected_container: Any = [] if isinstance(nxt, int) else {}
            if isinstance(tok, str):
                if not isinstance(cur, dict):
                    raise NativeBadRequestError(
                        f"Gemini partialArgs path conflict at {tok!r} in {raw_path!r}",
                        status_code=400,
                        provider="gemini",
                        error_code="invalid_partial_args_path",
                    )
                if tok not in cur or not isinstance(cur[tok], type(expected_container)):
                    cur[tok] = expected_container
                cur = cur[tok]
            elif isinstance(tok, int):
                if not isinstance(cur, list):
                    raise NativeBadRequestError(
                        f"Gemini partialArgs path conflict at [{tok}] in {raw_path!r}",
                        status_code=400,
                        provider="gemini",
                        error_code="invalid_partial_args_path",
                    )
                while len(cur) <= tok:
                    cur.append(None)
                if cur[tok] is None or not isinstance(cur[tok], type(expected_container)):
                    cur[tok] = expected_container
                cur = cur[tok]

        last = tokens[-1]
        if isinstance(last, str) and isinstance(cur, dict):
            if is_string and isinstance(cur.get(last), str):
                cur[last] += val
            else:
                cur[last] = val
        elif isinstance(last, int) and isinstance(cur, list):
            while len(cur) <= last:
                cur.append(None)
            if is_string and isinstance(cur[last], str):
                cur[last] += val
            else:
                cur[last] = val


def _extract_gemini_parts(
    parts: Iterable[Any],
    *,
    cand_idx: int = 0,
    tool_index_start: int = 0,
    active_partial_fc: Optional[Dict[int, Dict[str, Any]]] = None,
) -> Tuple[List[str], List[str], List[NativeToolCall], List[Dict[str, Any]], bool]:
    """Extract text, reasoning, tool calls, and ordered original model parts for replay (P1-18, P1-21, P1-11a)."""
    text_parts: List[str] = []
    reasoning_parts: List[str] = []
    tool_calls: List[NativeToolCall] = []
    ordered_parts: List[Dict[str, Any]] = []
    preserve_ordered_parts = False

    def _emit_function_call(
        *,
        fn_name: str,
        args_dict: Dict[str, Any],
        raw_id: str,
        sig_str: Optional[str],
    ) -> None:
        tc_idx = tool_index_start + len(tool_calls)
        args_str = json.dumps(args_dict or {}, ensure_ascii=False, sort_keys=True)
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
        fc_part: Dict[str, Any] = {
            "functionCall": {
                "name": fn_name,
                "args": copy.deepcopy(args_dict or {}),
                "id": call_id,
            }
        }
        if sig_str:
            fc_part["thoughtSignature"] = sig_str
        ordered_parts.append(fc_part)

    for part in parts:
        if not isinstance(part, Mapping):
            continue
        sig = part.get("thoughtSignature") or part.get("thought_signature")
        sig_str = str(sig) if sig else None
        if sig_str:
            preserve_ordered_parts = True

        if "text" in part and part.get("text") is not None:
            text_val = str(part["text"])
            if part.get("thought") is True:
                reasoning_parts.append(text_val)
                thought_part: Dict[str, Any] = {"text": text_val, "thought": True}
                if sig_str:
                    thought_part["thoughtSignature"] = sig_str
                    preserve_ordered_parts = True
                ordered_parts.append(thought_part)
            else:
                text_parts.append(text_val)
                text_block: Dict[str, Any] = {"text": text_val}
                if sig_str:
                    text_block["thoughtSignature"] = sig_str
                ordered_parts.append(text_block)
        elif isinstance(part.get("functionCall"), Mapping):
            fc = part["functionCall"]
            is_partial_frame = (
                active_partial_fc is not None
                and (
                    bool(fc.get("willContinue"))
                    or "partialArgs" in fc
                    or cand_idx in active_partial_fc
                )
            )
            if is_partial_frame and active_partial_fc is not None:
                state = active_partial_fc.setdefault(
                    cand_idx,
                    {"name": "", "id": "", "args": {}, "sig": None, "pending_leaf_paths": set()},
                )
                if fc.get("name"):
                    state["name"] = str(fc["name"])
                if fc.get("id"):
                    state["id"] = str(fc["id"])
                if sig_str and not state.get("sig"):
                    state["sig"] = sig_str
                if isinstance(fc.get("args"), Mapping):
                    state["args"].update(copy.deepcopy(dict(fc["args"])))
                if isinstance(fc.get("partialArgs"), list):
                    _apply_gemini_partial_args(
                        state["args"],
                        fc["partialArgs"],
                        state["pending_leaf_paths"],
                    )
                if fc.get("willContinue") or state["pending_leaf_paths"]:
                    continue
                completed = active_partial_fc.pop(cand_idx)
                _emit_function_call(
                    fn_name=completed["name"],
                    args_dict=completed["args"],
                    raw_id=completed["id"],
                    sig_str=completed.get("sig") or sig_str,
                )
            else:
                fn_name = str(fc.get("name") or "")
                raw_args = fc.get("args")
                args_dict = copy.deepcopy(dict(raw_args)) if isinstance(raw_args, Mapping) else {}
                raw_id = str(fc.get("id") or "").strip()
                _emit_function_call(
                    fn_name=fn_name,
                    args_dict=args_dict,
                    raw_id=raw_id,
                    sig_str=sig_str,
                )
        elif sig_str:
            # P1-18: Preserve signature-only parts verbatim for replay.
            ordered_parts.append({"thoughtSignature": sig_str})

    if tool_calls and (text_parts or reasoning_parts):
        preserve_ordered_parts = True

    return text_parts, reasoning_parts, tool_calls, ordered_parts, preserve_ordered_parts


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
        text_parts, reasoning_parts, tool_calls, ordered_parts, preserve_parts = _extract_gemini_parts(
            parts,
            cand_idx=cand_idx,
        )
        finish_reason = _map_gemini_finish_reason(
            cand.get("finishReason"),
            has_tool_calls=bool(tool_calls),
        )
        if finish_reason is None and tool_calls:
            finish_reason = "tool_calls"
        elif finish_reason is None:
            finish_reason = "stop"
        choices.append(
            NativeChoice(
                index=cand_idx,
                message=NativeMessage(
                    role="assistant",
                    content="".join(text_parts) if text_parts else None,
                    tool_calls=tool_calls or None,
                    reasoning_content="\n".join(reasoning_parts) if reasoning_parts else None,
                    provider_blocks=ordered_parts if preserve_parts else None,
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
    active_partial_fc_by_cand: Dict[int, Dict[str, Any]] = {}
    buffered_unsigned_parts_by_cand: Dict[int, List[Dict[str, Any]]] = {}
    emitted_ordered_by_cand: Dict[int, bool] = {}
    seen_candidates: Set[int] = set()
    finished_candidates: Set[int] = set()
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
            seen_candidates.add(cand_idx)
            content_obj = cand.get("content") if isinstance(cand.get("content"), Mapping) else {}
            parts = content_obj.get("parts") or []
            start_idx = tool_count_by_cand.get(cand_idx, 0)
            text_parts, reasoning_parts, tool_calls, ordered_parts, preserve_parts = _extract_gemini_parts(
                parts,
                cand_idx=cand_idx,
                tool_index_start=start_idx,
                active_partial_fc=active_partial_fc_by_cand,
            )
            if tool_calls:
                tool_count_by_cand[cand_idx] = start_idx + len(tool_calls)
                saw_tools_by_cand[cand_idx] = True

            # P1-11b: Normalize finishReason BEFORE adding to finished_candidates so blank
            # or FINISH_REASON_UNSPECIFIED never marks a candidate terminal.
            norm_finish = _normalize_gemini_finish_reason_raw(cand.get("finishReason"))
            if norm_finish is not None:
                finished_candidates.add(cand_idx)
            finish_reason = _map_gemini_finish_reason(
                norm_finish,
                has_tool_calls=saw_tools_by_cand.get(cand_idx, False),
            )
            # P1-9 & F7: Preserve ordered provider_blocks per candidate in SSE, including
            # leading unsigned text emitted in earlier frames before a tool call or signed part.
            emitted_blocks: Optional[List[Dict[str, Any]]] = None
            if ordered_parts:
                should_emit_ordered = (
                    preserve_parts
                    or bool(tool_calls)
                    or saw_tools_by_cand.get(cand_idx, False)
                    or emitted_ordered_by_cand.get(cand_idx, False)
                )
                if should_emit_ordered:
                    prior_unsigned = buffered_unsigned_parts_by_cand.pop(cand_idx, [])
                    emitted_blocks = prior_unsigned + ordered_parts
                    emitted_ordered_by_cand[cand_idx] = True
                else:
                    buffered_unsigned_parts_by_cand.setdefault(cand_idx, []).extend(ordered_parts)
            if not (text_parts or reasoning_parts or tool_calls or emitted_blocks or finish_reason):
                continue
            delta = NativeMessage(
                role="assistant",
                content="".join(text_parts) if text_parts else None,
                tool_calls=tool_calls or None,
                reasoning_content="\n".join(reasoning_parts) if reasoning_parts else None,
                provider_blocks=emitted_blocks,
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

    if active_partial_fc_by_cand:
        raise NativeIncompleteStreamError(
            "Gemini SSE stream ended with an unfinished streamed functionCall (willContinue=true)",
            provider=provider,
            secrets=secrets,
            error_code="incomplete_stream",
        )

    if not finished_candidates or not seen_candidates.issubset(finished_candidates):
        missing = sorted(seen_candidates - finished_candidates)
        raise NativeIncompleteStreamError(
            f"Gemini SSE stream ended without a terminal finishReason for candidate(s): {missing or [0]}",
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
    skip_sensitive = bool(kwargs.get("_dsa_skip_sensitive_caller_headers"))
    merge_header_overrides(headers, {"extra_headers": entry.extra_headers})
    merge_header_overrides(
        headers,
        kwargs,
        resolve_env_fn=resolve_env_reference,
        safe_allowlist_only=skip_sensitive,
    )

    query_keys = {k.lower() for k, _ in parse_qsl(urlsplit(url).query, keep_blank_values=True)}
    api_key = entry.api_key or (None if skip_sensitive else kwargs.get("api_key"))
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
