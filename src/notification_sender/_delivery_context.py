# -*- coding: utf-8 -*-
"""Per-dispatch delivery certainty tracking shared with notification senders."""

from __future__ import annotations

import contextvars
from dataclasses import dataclass
import re
from typing import Optional, Tuple
from urllib.parse import urlsplit

import requests

_VALID_HTTP_HEADER_NAME_RE = re.compile(rb"^[!#$%&'*+\-.^_`|~0-9A-Za-z]+$")


def is_valid_http_url(value: Optional[str]) -> bool:
    """Return True when value is a whitespace-free HTTP(S) URL accepted by Requests."""
    if not isinstance(value, str) or not value or any(char.isspace() for char in value):
        return False
    try:
        parsed = urlsplit(value)
        _ = parsed.port
    except ValueError:
        return False
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return False
    try:
        requests.Request("POST", value).prepare()
    except (requests.exceptions.RequestException, ValueError, TypeError):
        return False
    return True


def _has_encodable_http_headers(headers: Optional[dict]) -> bool:
    """Verify header names are valid ASCII tokens and values are Latin-1 encodable without control chars."""
    if not headers:
        return True
    for key, value in headers.items():
        if not isinstance(key, str) or not key:
            return False
        try:
            key_bytes = key.encode("ascii")
        except UnicodeEncodeError:
            return False
        if _VALID_HTTP_HEADER_NAME_RE.fullmatch(key_bytes) is None:
            return False
        if value is None:
            continue
        if isinstance(value, bytes):
            raw_bytes = value
        elif isinstance(value, str):
            try:
                raw_bytes = value.encode("latin-1")
            except UnicodeEncodeError:
                return False
        else:
            return False
        if any((b < 0x20 and b != 0x09) or b == 0x7F for b in raw_bytes):
            return False
    return True


def is_valid_http_headers(headers: Optional[dict]) -> bool:
    """Return True when every header name and value is accepted by Requests and wire-encodable."""
    if not _has_encodable_http_headers(headers):
        return False
    if not headers:
        return True
    try:
        requests.Request("POST", "https://example.invalid", headers=headers).prepare()
    except (requests.exceptions.RequestException, ValueError, TypeError):
        return False
    return True


def validate_http_post_request(
    url: Optional[str],
    *,
    headers: Optional[dict] = None,
    json: object = None,
    data: object = None,
    files: object = None,
) -> bool:
    """Validate an HTTP(S) POST request via Requests preparation before any transport send."""
    if not is_valid_http_url(url) or not is_valid_http_headers(headers):
        return False
    try:
        prepared = requests.Request(
            "POST",
            url,
            headers=headers,
            json=json,
            data=data,
            files=files,
        ).prepare()
    except (requests.exceptions.RequestException, ValueError, TypeError):
        return False
    if not _has_encodable_http_headers(prepared.headers):
        return False
    return True


@dataclass
class DeliveryAttemptState:
    """Track whether a channel failure definitely prevented delivery or remained ambiguous."""

    at_most_once: bool = False
    confirmed_absent: bool = False
    ambiguous: bool = False
    any_delivered: bool = False
    error_code: Optional[str] = None


_current_delivery_state: contextvars.ContextVar[Optional[DeliveryAttemptState]] = contextvars.ContextVar(
    "_current_delivery_state",
    default=None,
)


def is_at_most_once_delivery() -> bool:
    """Return True when the active send context forbids ambiguous internal retries."""
    state = _current_delivery_state.get()
    return bool(state is not None and state.at_most_once)


def is_delivery_ambiguous() -> bool:
    """Return True when the active send context has already observed an ambiguous failure."""
    state = _current_delivery_state.get()
    return bool(state is not None and state.ambiguous)


def begin_delivery_attempt(*, at_most_once: bool = False) -> Tuple[DeliveryAttemptState, contextvars.Token]:
    """Activate a fresh per-channel delivery certainty context and return its token."""
    state = DeliveryAttemptState(at_most_once=bool(at_most_once))
    token = _current_delivery_state.set(state)
    return state, token


def end_delivery_attempt(token: contextvars.Token) -> None:
    """Restore the prior delivery certainty context."""
    _current_delivery_state.reset(token)


def record_delivery_confirmed_absent(error_code: Optional[str] = None) -> None:
    """Record a pre-send rejection or connect failure when no prior request was sent."""
    state = _current_delivery_state.get()
    if state is None or state.any_delivered or state.ambiguous:
        return
    state.confirmed_absent = True
    if error_code and not state.error_code:
        state.error_code = str(error_code)


def record_delivery_ambiguous(error_code: Optional[str] = None) -> None:
    """Record an ambiguous transport/server outcome where external receipt is uncertain."""
    state = _current_delivery_state.get()
    if state is None:
        return
    state.ambiguous = True
    state.confirmed_absent = False
    if error_code:
        state.error_code = str(error_code)


def record_delivery_succeeded() -> None:
    """Record that at least one external request in this channel dispatch succeeded."""
    state = _current_delivery_state.get()
    if state is None:
        return
    state.any_delivered = True
    state.confirmed_absent = False
