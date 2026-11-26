# -*- coding: utf-8 -*-
"""Line-buffered Server-Sent Events (SSE) parser for native HTTPX LLM streaming."""

from __future__ import annotations

import codecs
from dataclasses import dataclass
import json
import logging
from typing import Any, Dict, Iterable, Iterator, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SSEEvent:
    """Single parsed Server-Sent Events frame."""

    event: str = "message"
    data: str = ""
    id: Optional[str] = None
    retry: Optional[int] = None


def iter_sse_lines(byte_chunks: Iterable[bytes]) -> Iterator[str]:
    """Decode UTF-8 chunks incrementally and emit lines across CR/LF/CRLF boundaries."""
    decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
    buf = ""
    skip_next_lf = False

    def _drain(force: bool) -> Iterator[str]:
        nonlocal buf, skip_next_lf
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
                break

            if cr_idx != -1 and (lf_idx == -1 or cr_idx < lf_idx):
                line = buf[:cr_idx]
                rest = buf[cr_idx + 1:]
                if rest.startswith("\n"):
                    buf = rest[1:]
                elif rest == "" and not force:
                    buf = ""
                    skip_next_lf = True
                    yield line
                    break
                else:
                    buf = rest
                yield line
            else:
                line = buf[:lf_idx]
                buf = buf[lf_idx + 1:]
                yield line

        if force and buf:
            yield buf
            buf = ""

    for raw_chunk in byte_chunks:
        if not raw_chunk:
            continue
        decoded = decoder.decode(raw_chunk, final=False)
        if decoded:
            buf += decoded
            yield from _drain(force=False)

    tail = decoder.decode(b"", final=True)
    if tail:
        buf += tail
    yield from _drain(force=True)


def iter_sse_events(byte_chunks: Iterable[bytes]) -> Iterator[SSEEvent]:
    """Parse an SSE byte stream into framed :class:`SSEEvent` objects."""
    event_name = "message"
    data_lines: list[str] = []
    last_event_id: Optional[str] = None
    retry_ms: Optional[int] = None

    def _flush_event() -> Optional[SSEEvent]:
        nonlocal event_name, data_lines
        if not data_lines and event_name == "message":
            return None
        ev = SSEEvent(
            event=event_name or "message",
            data="\n".join(data_lines),
            id=last_event_id,
            retry=retry_ms,
        )
        event_name = "message"
        data_lines = []
        return ev

    for line in iter_sse_lines(byte_chunks):
        if line == "":
            ev = _flush_event()
            if ev is not None and ev.data != "":
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
            data_lines.append(value)
        elif field == "event":
            event_name = value or "message"
        elif field == "id":
            if "\x00" not in value:
                last_event_id = value
        elif field == "retry":
            if value.isdigit():
                retry_ms = int(value)

    trailing = _flush_event()
    if trailing is not None and trailing.data != "":
        yield trailing


def iter_sse_json_events(byte_chunks: Iterable[bytes]) -> Iterator[Tuple[str, Dict[str, Any]]]:
    """Yield ``(event_name, payload_dict)`` pairs from an SSE stream, stopping at ``[DONE]``."""
    for ev in iter_sse_events(byte_chunks):
        raw_data = ev.data.strip()
        if not raw_data:
            continue
        if raw_data == "[DONE]":
            break
        try:
            parsed = json.loads(raw_data)
        except ValueError:
            logger.debug("[SSE] Ignoring non-JSON data payload: %s", raw_data[:120])
            continue
        if isinstance(parsed, dict):
            yield ev.event, parsed
        else:
            logger.debug("[SSE] Ignoring non-object JSON payload of type %s", type(parsed).__name__)
