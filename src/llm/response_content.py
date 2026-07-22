"""Helpers for normalizing provider response text."""

from __future__ import annotations


_THINK_OPEN_TAG = "<think>"
_THINK_CLOSE_TAG = "</think>"


def strip_leading_think_wrapper(value: str) -> str:
    """Remove one complete leading ``<think>`` wrapper from a response.

    The match is deliberately anchored at the start of the response.  This
    keeps literal ``<think>`` markup inside a JSON string or ordinary answer
    untouched and leaves malformed/unclosed wrappers for strict validation to
    reject instead of guessing where the final answer begins.
    """

    text = str(value or "").strip()
    lowered = text.lower()
    if not lowered.startswith(_THINK_OPEN_TAG):
        return text

    close_index = lowered.find(_THINK_CLOSE_TAG, len(_THINK_OPEN_TAG))
    if close_index < 0:
        return text

    return text[close_index + len(_THINK_CLOSE_TAG):].strip()
