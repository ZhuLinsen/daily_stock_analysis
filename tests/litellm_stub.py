# -*- coding: utf-8 -*-
"""Shared test helper to keep litellm imports lightweight in unit tests."""

from contextlib import contextmanager
from importlib import import_module
import sys
import types
from typing import Iterator


def ensure_litellm_stub() -> None:
    """Install a minimal litellm stub unless a test already provided one."""
    existing = sys.modules.get("litellm")
    if getattr(existing, "__dsa_test_stub__", False):
        return
    if existing is not None:
        try:
            import_module("litellm.types.utils")
            return
        except ModuleNotFoundError:
            for module_name in ("litellm.types.utils", "litellm.types", "litellm"):
                sys.modules.pop(module_name, None)

    litellm_stub = types.ModuleType("litellm")
    litellm_stub.__dsa_test_stub__ = True

    class _DummyRouter:  # pragma: no cover
        pass

    class _DummyRateLimitError(Exception):
        pass

    class _DummyContextWindowExceededError(Exception):
        pass

    class _DummyUsage:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

        def model_dump(self):
            return dict(self.__dict__)

        def dict(self):
            return dict(self.__dict__)

    litellm_types_stub = types.ModuleType("litellm.types")
    litellm_types_utils_stub = types.ModuleType("litellm.types.utils")
    litellm_types_utils_stub.Usage = _DummyUsage
    litellm_types_stub.utils = litellm_types_utils_stub

    litellm_stub.Router = _DummyRouter
    litellm_stub.RateLimitError = _DummyRateLimitError
    litellm_stub.ContextWindowExceededError = _DummyContextWindowExceededError
    litellm_stub.completion = lambda **kwargs: None
    litellm_stub.types = litellm_types_stub
    sys.modules["litellm"] = litellm_stub
    sys.modules["litellm.types"] = litellm_types_stub
    sys.modules["litellm.types.utils"] = litellm_types_utils_stub


def remove_litellm_stub() -> None:
    """Remove this stub so tests that need real LiteLLM types can import them."""
    if not getattr(sys.modules.get("litellm"), "__dsa_test_stub__", False):
        return

    for module_name in ("litellm.types.utils", "litellm.types", "litellm"):
        sys.modules.pop(module_name, None)


def is_real_package_installed(name: str) -> bool:
    """Check whether a real package is importable without mutating sys.modules or importing it."""
    for finder in sys.meta_path:
        find_spec = getattr(finder, "find_spec", None)
        if not callable(find_spec):
            continue
        try:
            spec = find_spec(name, None)
        except (ImportError, ValueError, AttributeError):
            return False
        if spec is not None:
            return True
    return False


@contextmanager
def without_litellm_stub() -> Iterator[None]:
    """Temporarily remove the litellm test stub and restore it if real litellm is not loaded."""
    had_stub = bool(getattr(sys.modules.get("litellm"), "__dsa_test_stub__", False))
    saved = {
        module_name: sys.modules[module_name]
        for module_name in ("litellm", "litellm.types", "litellm.types.utils")
        if module_name in sys.modules
    }
    if had_stub:
        remove_litellm_stub()
    try:
        yield
    finally:
        if had_stub and "litellm" not in sys.modules:
            for module_name, mod in saved.items():
                sys.modules[module_name] = mod
