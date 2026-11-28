# -*- coding: utf-8 -*-
"""Line-buffered Server-Sent Events (SSE) parser for native HTTPX LLM streaming."""

from __future__ import annotations

import codecs
from dataclasses import dataclass
import json
import logging
from typing import Any, Callable, Dict, Iterable, Iterator, Optional, Tuple

from src.llm.native_types import NativeAPIError, NativeIncompleteStreamError

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SSEEvent:
    """Single parsed Server-Sent Events frame."""

    event: str = "message"
    data: str = ""
    id: Optional[str] = None
    retry: Optional[int] = None


@dataclass
class SSEStreamState:
    """Mutable stream framing summary populated while iterating SSE JSON events."""

    saw_done: bool = False
    event_count: int = 0


DEFAULT_MAX_SSE_LINE_CHARS = 10 * 1024 * 1024
DEFAULT_MAX_SSE_EVENT_CHARS = 20 * 1024 * 1024


def iter_sse_lines(
    byte_chunks: Iterable[bytes],
    *,
    cancel_check: Optional[Callable[[], None]] = None,
    max_line_chars: int = DEFAULT_MAX_SSE_LINE_CHARS,
) -> Iterator[str]:
    """Decode UTF-8 chunks incrementally, strip leading BOM, and emit complete CR/LF/CRLF lines.

    Raises :class:`NativeIncompleteStreamError` if EOF occurs mid-line without a
    terminating CR or LF, preventing silently truncated payloads from being
    treated as successful completions. Enforces ``max_line_chars`` to guard
    against unbounded memory growth on pathological streams.
    """
    decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
    buf = ""
    skip_next_lf = False
    bom_checked = False
    line_limit = max(1024, int(max_line_chars))

    def _strip_leading_bom() -> None:
        nonlocal buf, bom_checked
        if not bom_checked and buf:
            if buf.startswith("\ufeff"):
                buf = buf[1:]
            bom_checked = True

    def _drain(final: bool) -> Iterator[str]:
        nonlocal buf, skip_next_lf
        _strip_leading_bom()
        while buf:
            if skip_next_lf:
                if buf[0] == "\n":
                    buf = buf[1:]
                skip_next_lf = False
                if not buf:
                    break

            cr_idx = buf.find("\r")
            lf_idx = buf.find("\n")
            if cr_idx == -1 and lf_idx == -1:
                if len(buf) > line_limit:
                    raise NativeAPIError(
                        f"SSE line exceeded maximum buffer size ({line_limit} chars)",
                        error_code="sse_frame_too_large",
                    )
                break

            if cr_idx != -1 and (lf_idx == -1 or cr_idx < lf_idx):
                line = buf[:cr_idx]
                if len(line) > line_limit:
                    raise NativeAPIError(
                        f"SSE line exceeded maximum buffer size ({line_limit} chars)",
                        error_code="sse_frame_too_large",
                    )
                rest = buf[cr_idx + 1 :]
                if rest.startswith("\n"):
                    buf = rest[1:]
                elif rest == "" and not final:
                    buf = ""
                    skip_next_lf = True
                    yield line
                    break
                else:
                    buf = rest
                yield line
            else:
                line = buf[:lf_idx]
                if len(line) > line_limit:
                    raise NativeAPIError(
                        f"SSE line exceeded maximum buffer size ({line_limit} chars)",
                        error_code="sse_frame_too_large",
                    )
                buf = buf[lf_idx + 1 :]
                yield line

    for raw_chunk in byte_chunks:
        if cancel_check is not None:
            cancel_check()
        if not raw_chunk:
            continue
        decoded = decoder.decode(raw_chunk, final=False)
        if decoded:
            buf += decoded
            yield from _drain(final=False)

    if cancel_check is not None:
        cancel_check()
    tail = decoder.decode(b"", final=True)
    if tail:
        buf += tail
    yield from _drain(final=True)

    if buf:
        raise NativeIncompleteStreamError(
            "SSE stream ended with an unterminated trailing line at EOF",
            error_code="incomplete_stream",
        )


def iter_sse_events(
    byte_chunks: Iterable[bytes],
    *,
    cancel_check: Optional[Callable[[], None]] = None,
    max_line_chars: int = DEFAULT_MAX_SSE_LINE_CHARS,
    max_event_chars: int = DEFAULT_MAX_SSE_EVENT_CHARS,
) -> Iterator[SSEEvent]:
    """Parse an SSE byte stream into blank-line-delimited :class:`SSEEvent` frames.

    Does NOT flush an unterminated event frame at EOF: reaching EOF with pending
    ``data``/``event`` lines raises :class:`NativeIncompleteStreamError`.
    Preserves empty ``data:`` frames per WHATWG SSE framing rules.
    """
    event_name = "message"
    data_lines: list[str] = []
    event_chars = 0
    has_pending_fields = False
    last_event_id: Optional[str] = None
    retry_ms: Optional[int] = None
    event_limit = max(1024, int(max_event_chars))

    def _flush_event() -> Optional[SSEEvent]:
        nonlocal event_name, data_lines, event_chars, has_pending_fields
        if not data_lines and not has_pending_fields:
            return None
        ev: Optional[SSEEvent] = None
        if data_lines:
            ev = SSEEvent(
                event=event_name or "message",
                data="\n".join(data_lines),
                id=last_event_id,
                retry=retry_ms,
            )
        event_name = "message"
        data_lines = []
        event_chars = 0
        has_pending_fields = False
        return ev

    for line in iter_sse_lines(
        byte_chunks,
        cancel_check=cancel_check,
        max_line_chars=max_line_chars,
    ):
        if line == "":
            ev = _flush_event()
            if ev is not None:
                yield ev
            continue

        if line.startswith(":"):
            # SSE comment / keepalive frame.
            continue

        if ":" in line:
            field, value = line.split(":", 1)
            if value.startswith(" "):
                value = value[1:]
        else:
            field, value = line, ""

        if field == "data":
            event_chars += len(value) + (1 if data_lines else 0)
            if event_chars > event_limit:
                raise NativeAPIError(
                    f"SSE event exceeded maximum buffer size ({event_limit} chars)",
                    error_code="sse_frame_too_large",
                )
            data_lines.append(value)
            has_pending_fields = True
        elif field == "event":
            event_name = value or "message"
            has_pending_fields = True
        elif field == "id":
            if "\x00" not in value:
                last_event_id = value
        elif field == "retry":
            if value.isdigit():
                retry_ms = int(value)

    if data_lines or has_pending_fields:
        raise NativeIncompleteStreamError(
            "SSE stream reached EOF with an unterminated event frame",
            error_code="incomplete_stream",
        )


def iter_sse_json_events(
    byte_chunks: Iterable[bytes],
    *,
    state: Optional[SSEStreamState] = None,
    stop_on_done: bool = True,
    provider: str = "openai",
    secrets: Iterable[str] = (),
    cancel_check: Optional[Callable[[], None]] = None,
) -> Iterator[Tuple[str, Dict[str, Any]]]:
    """Yield ``(event_name, payload_dict)`` pairs from an SSE stream, recording ``[DONE]``."""
    for ev in iter_sse_events(byte_chunks, cancel_check=cancel_check):
        raw_data = ev.data.strip()
        if not raw_data:
            continue
        if raw_data == "[DONE]":
            if state is not None:
                state.saw_done = True
            if stop_on_done:
                break
            continue
        try:
            parsed = json.loads(raw_data)
        except ValueError as exc:
            raise NativeAPIError(
                f"Malformed JSON in SSE event '{ev.event}': {raw_data[:200]}",
                provider=provider,
                body=raw_data[:512],
                secrets=secrets,
                error_code="malformed_sse_json",
            ) from exc
        if isinstance(parsed, dict):
            if state is not None:
                state.event_count += 1
            yield ev.event, parsed
        else:
            logger.debug(
                "[SSE] Ignoring non-object JSON payload of type %s",
                type(parsed).__name__,
            )
