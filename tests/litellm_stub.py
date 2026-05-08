# -*- coding: utf-8 -*-
"""Shared test helper to keep litellm imports lightweight in unit tests."""

import sys
import types


def ensure_litellm_stub() -> None:
    """Install a minimal litellm stub unless a test already provided one."""
    if "litellm" in sys.modules:
        return

    litellm_stub = types.ModuleType("litellm")

    class _DummyRouter:  # pragma: no cover
        pass

    class _DummyRateLimitError(Exception):
        pass

    class _DummyContextWindowExceededError(Exception):
        pass

    litellm_stub.Router = _DummyRouter
    litellm_stub.RateLimitError = _DummyRateLimitError
    litellm_stub.ContextWindowExceededError = _DummyContextWindowExceededError
    litellm_stub.completion = lambda **kwargs: None
    sys.modules["litellm"] = litellm_stub
