# -*- coding: utf-8 -*-
"""Unit tests, integration tests, and repo-wide AST guard for the Phase 1 LLM transport facade."""

from __future__ import annotations

import ast
import asyncio
import importlib.abc
import importlib.machinery
import logging
import math
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
from types import ModuleType, SimpleNamespace
from typing import Any, Dict, List, Mapping, Optional
from unittest.mock import MagicMock, patch

import pytest

from src.agent import chat_context
from src.agent.llm_adapter import LLMToolAdapter, register_fallback_model_pricing
from src.analyzer import GeminiAnalyzer
from src.config import Config, get_litellm_model_providers, normalize_llm_channel_model
from src.llm.transport import (
    DeploymentSpec,
    LLMTransport,
    LiteLLMPatchProxy,
    LiteLLMTransport,
    can_register_model,
    create_litellm_compat_proxy,
    create_router,
    dispatch_completion,
    estimate_tokens,
    estimate_tokens_fallback,
    find_unresolved_env_var,
    get_model_cost,
    get_model_providers,
    get_transport,
    normalize_deployment_spec,
    normalize_deployment_specs,
    normalize_model_list_entries,
    register_model,
    reset_transport_cache,
    resolve_env_reference,
    resolve_exception_types,
    resolve_litellm_params_env,
    set_default_transport,
    silence_litellm_logs,
    use_transport,
)
from src.services import image_stock_extractor, screening_service
from src.services.screening import ranker
from src.services.system_config_service import SystemConfigService

REPO_ROOT = Path(__file__).resolve().parent.parent


class _RecordingTransport:
    """Fake LLMTransport recording all operations without touching real litellm."""

    def __init__(self, response_text: str = '{"status": "ok"}') -> None:
        self.response_text = response_text
        self.completion_calls: List[Dict[str, Any]] = []
        self.router_calls: List[Dict[str, Any]] = []
        self.router_completion_calls: List[Dict[str, Any]] = []
        self.pricing_calls: List[Dict[str, Any]] = []
        self.silence_calls: int = 0
        self.token_calls: List[Dict[str, Any]] = []
        self.cost_map: Dict[str, Any] = {}
        self.providers: frozenset[str] = frozenset({"openai", "anthropic", "gemini", "custom-transport"})

    def completion(self, **kwargs: Any) -> Any:
        self.completion_calls.append(dict(kwargs))
        if kwargs.get("stream"):
            return iter(
                [
                    SimpleNamespace(
                        choices=[SimpleNamespace(delta=SimpleNamespace(content="OK"))]
                    )
                ]
            )
        if kwargs.get("tools"):
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content="",
                            tool_calls=[
                                SimpleNamespace(
                                    id="call_1",
                                    function=SimpleNamespace(
                                        name="dsa_probe_echo",
                                        arguments='{"text": "ok"}',
                                    ),
                                )
                            ],
                        )
                    )
                ],
                usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5, total_tokens=15),
            )
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content=self.response_text,
                        tool_calls=None,
                    )
                )
            ],
            usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5, total_tokens=15),
        )

    def create_router(self, model_list: List[Dict[str, Any]], **kwargs: Any) -> Any:
        self.router_calls.append({"model_list": model_list, "kwargs": dict(kwargs)})
        parent = self

        class _FakeRouter:
            _dsa_accepts_transport_metadata = True

            def __init__(self) -> None:
                self.model_list = model_list

            def completion(self, **call_kwargs: Any) -> Any:
                parent.router_completion_calls.append(dict(call_kwargs))
                return parent.completion(**call_kwargs)

        return _FakeRouter()

    def can_register_model(self) -> bool:
        return True

    def register_model(self, model_cost: Mapping[str, Any]) -> None:
        self.pricing_calls.append(dict(model_cost))
        self.cost_map.update(model_cost)

    def get_model_cost(self) -> Dict[str, Any]:
        return dict(self.cost_map)

    def estimate_tokens(self, text: str, *, model: Optional[str] = None) -> int:
        self.token_calls.append({"text": text, "model": model})
        return 42

    def get_model_providers(self) -> frozenset[str]:
        return self.providers

    def disable_streaming_logging(self) -> None:
        return None

    def silence_logs(self) -> None:
        self.silence_calls += 1

    def resolve_exception(self, name: str) -> type[BaseException]:
        class _RecordedTransportError(Exception):
            pass

        _RecordedTransportError.__name__ = f"Recorded{name}"
        return _RecordedTransportError


def _is_litellm_name_constant(node: Optional[ast.AST]) -> bool:
    return (
        isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and (node.value == "litellm" or node.value.startswith("litellm."))
    )


def _call_target_module_arg(node: ast.Call) -> Optional[ast.AST]:
    if node.args:
        return node.args[0]
    for kw in node.keywords:
        if kw.arg == "name":
            return kw.value
    return None


def _is_sys_modules_expr(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "sys"
        and node.attr == "modules"
    )


def _find_litellm_boundary_violations(source: str, rel_path: str) -> List[str]:
    """Inspect a Python module AST for direct LiteLLM coupling outside src/llm/transport.py."""
    forbidden_litellm_attrs = {
        "completion",
        "acompletion",
        "Router",
        "register_model",
        "token_counter",
    }
    tree = ast.parse(source, filename=rel_path)
    violations: List[str] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "litellm" or alias.name.startswith("litellm."):
                    violations.append(f"{rel_path}:{node.lineno}: direct import {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            module_name = node.module or ""
            if module_name == "litellm" or module_name.startswith("litellm."):
                violations.append(f"{rel_path}:{node.lineno}: direct from-import {module_name}")
        elif isinstance(node, ast.Subscript):
            if _is_sys_modules_expr(node.value) and _is_litellm_name_constant(node.slice):
                violations.append(
                    f"{rel_path}:{node.lineno}: direct sys.modules[{node.slice.value!r}] access"
                )
        elif isinstance(node, ast.Call):
            func = node.func
            first_or_name_arg = _call_target_module_arg(node)
            if (
                (
                    (isinstance(func, ast.Attribute) and func.attr == "import_module")
                    or (isinstance(func, ast.Name) and func.id == "import_module")
                )
                and _is_litellm_name_constant(first_or_name_arg)
            ):
                violations.append(
                    f"{rel_path}:{node.lineno}: dynamic import_module({first_or_name_arg.value!r})"
                )
            elif (
                isinstance(func, ast.Name)
                and func.id == "__import__"
                and _is_litellm_name_constant(first_or_name_arg)
            ):
                violations.append(
                    f"{rel_path}:{node.lineno}: dynamic __import__({first_or_name_arg.value!r})"
                )
            elif (
                isinstance(func, ast.Attribute)
                and _is_sys_modules_expr(func.value)
                and func.attr in {"get", "pop", "setdefault"}
                and node.args
                and _is_litellm_name_constant(node.args[0])
            ):
                violations.append(
                    f"{rel_path}:{node.lineno}: direct sys.modules.{func.attr}({node.args[0].value!r})"
                )
            elif (
                isinstance(func, ast.Attribute)
                and isinstance(func.value, ast.Name)
                and func.value.id == "litellm"
                and func.attr in forbidden_litellm_attrs
            ):
                violations.append(f"{rel_path}:{node.lineno}: direct call litellm.{func.attr}()")
            elif (
                isinstance(func, ast.Name)
                and func.id == "Router"
                and rel_path
                in {
                    "src/analyzer.py",
                    "src/agent/llm_adapter.py",
                    "src/services/screening/ranker.py",
                }
            ):
                violations.append(f"{rel_path}:{node.lineno}: direct Router() call")

    return violations


def test_repo_wide_ast_guard_forbids_direct_litellm_imports_and_calls() -> None:
    """AST guard preventing direct litellm imports/loads/sys.modules/SDK calls outside src/llm/transport.py."""
    scan_roots = [
        REPO_ROOT / "src",
        REPO_ROOT / "api",
        REPO_ROOT / "bot",
        REPO_ROOT / "data_provider",
        REPO_ROOT / "main.py",
        REPO_ROOT / "server.py",
    ]
    exempt_files = {
        (REPO_ROOT / "src" / "llm" / "transport.py").resolve(),
    }

    py_files: List[Path] = []
    for root in scan_roots:
        if root.is_file():
            py_files.append(root)
        elif root.is_dir():
            py_files.extend(sorted(root.rglob("*.py")))

    violations: List[str] = []
    for path in py_files:
        if path.resolve() in exempt_files:
            continue
        rel = path.relative_to(REPO_ROOT).as_posix()
        violations.extend(_find_litellm_boundary_violations(path.read_text(encoding="utf-8"), rel))

    assert violations == []


def test_ast_guard_catches_all_bypass_patterns_and_allows_clean_code() -> None:
    """Positive and negative unit tests verifying AST guard catches indirect LiteLLM import bypasses."""
    bad_snippets = [
        "import litellm\n",
        "from litellm.types.utils import LlmProviders\n",
        "import importlib\nimportlib.import_module('litellm')\n",
        "from importlib import import_module\nimport_module('litellm.types.utils')\n",
        "from importlib import import_module\nimport_module(name='litellm')\n",
        "__import__(name='litellm')\n",
        "import sys\nmod = sys.modules['litellm']\n",
        "import sys\nmod = sys.modules.get('litellm.types.utils')\n",
        "litellm.completion(model='openai/gpt-4o')\n",
    ]
    for snippet in bad_snippets:
        assert _find_litellm_boundary_violations(snippet, "src/example.py"), snippet

    assert _find_litellm_boundary_violations("Router(model_list=[])\n", "src/analyzer.py")
    assert _find_litellm_boundary_violations(
        "from src.llm.transport import dispatch_completion\ndispatch_completion(model='openai/gpt-4o')\n",
        "src/example.py",
    ) == []


def test_importing_runtime_modules_does_not_eagerly_import_litellm() -> None:
    """Importing runtime modules must not trigger litellm import at module load time."""
    probe = """
import sys
import src.llm
import src.llm.transport
import src.config
import src.analyzer
import src.agent.llm_adapter
import src.agent.chat_context
import src.services.image_stock_extractor
import src.services.screening.ranker
import src.services.screening_service
import src.services.system_config_service
assert "litellm" not in sys.modules, f"litellm eagerly imported"
"""
    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO_ROOT)
    proc = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0, f"stderr={proc.stderr}\nstdout={proc.stdout}"


def test_load_litellm_sets_local_model_cost_map_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """Lazy _load_litellm() sets LITELLM_LOCAL_MODEL_COST_MAP=True when unset and respects explicit values."""
    seen_env: List[Optional[str]] = []
    fake_mod = SimpleNamespace(disable_streaming_logging=False)

    def _fake_import(name: str) -> Any:
        assert name == "litellm"
        seen_env.append(os.environ.get("LITELLM_LOCAL_MODEL_COST_MAP"))
        return fake_mod

    monkeypatch.delenv("LITELLM_LOCAL_MODEL_COST_MAP", raising=False)
    monkeypatch.delitem(sys.modules, "litellm", raising=False)
    monkeypatch.setattr("src.llm.transport.importlib.import_module", _fake_import)

    loaded = LiteLLMTransport._load_litellm()
    assert loaded is fake_mod
    assert seen_env == ["True"]
    assert os.environ.get("LITELLM_LOCAL_MODEL_COST_MAP") == "True"
    assert fake_mod.disable_streaming_logging is True

    # Explicit user configuration is preserved.
    seen_env.clear()
    monkeypatch.setenv("LITELLM_LOCAL_MODEL_COST_MAP", "False")
    LiteLLMTransport._load_litellm()
    assert seen_env == ["False"]
    assert os.environ.get("LITELLM_LOCAL_MODEL_COST_MAP") == "False"


def test_load_litellm_is_thread_safe_during_slow_first_import(monkeypatch: pytest.MonkeyPatch) -> None:
    """Concurrent first _load_litellm() calls wait on Python's import lock instead of seeing half-init module."""
    entered_exec = threading.Event()
    allow_finish = threading.Event()
    exec_count = 0

    class _SlowFakeLoader(importlib.abc.Loader):
        def create_module(self, spec: Any) -> Optional[ModuleType]:
            return None

        def exec_module(self, module: ModuleType) -> None:
            nonlocal exec_count
            exec_count += 1
            entered_exec.set()
            assert allow_finish.wait(timeout=5)
            time.sleep(0.02)
            module.completion = lambda **kw: kw  # type: ignore[attr-defined]
            module.Router = object  # type: ignore[attr-defined]

    class _SlowFakeFinder(importlib.abc.MetaPathFinder):
        def find_spec(self, fullname: str, path: Any, target: Any = None) -> Any:
            if fullname == "litellm":
                return importlib.machinery.ModuleSpec("litellm", _SlowFakeLoader())
            return None

    saved_litellm = sys.modules.pop("litellm", None)
    finder = _SlowFakeFinder()
    sys.meta_path.insert(0, finder)
    results: List[Any] = []
    errors: List[BaseException] = []

    def _worker() -> None:
        try:
            mod = LiteLLMTransport._load_litellm()
            assert callable(getattr(mod, "completion", None))
            assert getattr(mod, "Router", None) is object
            results.append(mod)
        except BaseException as exc:  # pragma: no cover - diagnostic capture
            errors.append(exc)

    try:
        t1 = threading.Thread(target=_worker)
        t2 = threading.Thread(target=_worker)
        t1.start()
        assert entered_exec.wait(timeout=5)
        t2.start()
        time.sleep(0.03)
        allow_finish.set()
        t1.join(timeout=5)
        t2.join(timeout=5)
    finally:
        sys.meta_path.remove(finder)
        sys.modules.pop("litellm", None)
        if saved_litellm is not None:
            sys.modules["litellm"] = saved_litellm

    assert errors == []
    assert exec_count == 1
    assert len(results) == 2
    assert results[0] is results[1]


def test_litellm_transport_encodes_responses_and_strips_metadata_across_direct_and_router() -> None:
    """LiteLLMTransport encodes Responses wire model and strips api_surface/wire_protocol everywhere."""
    captured: List[Dict[str, Any]] = []
    router_init_lists: List[List[Dict[str, Any]]] = []
    router_comp_calls: List[Dict[str, Any]] = []

    class _FakeSDKRouter:
        def __init__(self, *, model_list: List[Dict[str, Any]], **kwargs: Any) -> None:
            router_init_lists.append(model_list)
            self.kwargs = kwargs

        def completion(self, **kwargs: Any) -> str:
            router_comp_calls.append(dict(kwargs))
            return "from-sdk-router"

    def _fake_completion(**kwargs: Any) -> str:
        captured.append(dict(kwargs))
        return "ok"

    fake_litellm = SimpleNamespace(
        completion=_fake_completion,
        Router=_FakeSDKRouter,
        register_model=MagicMock(),
        model_cost={"gpt-4o": {"input_cost_per_token": 0.1}},
        set_verbose=True,
        suppress_debug_info=False,
        disable_streaming_logging=False,
        token_counter=MagicMock(return_value=19),
    )

    transport = LiteLLMTransport()
    assert isinstance(transport, LLMTransport)
    with patch.dict(sys.modules, {"litellm": fake_litellm}, clear=False):
        # Chat surface is stripped cleanly without altering wire model.
        assert (
            transport.completion(
                model="openai/gpt-5",
                messages=[{"role": "user", "content": "hi"}],
                api_surface="chat_completions",
                wire_protocol="openai_chat",
                extra_headers={"X-Relay": "1"},
            )
            == "ok"
        )
        assert captured[0] == {
            "model": "openai/gpt-5",
            "messages": [{"role": "user", "content": "hi"}],
            "extra_headers": {"X-Relay": "1"},
        }

        # Responses surface is encoded onto wire model before stripping internal keys.
        transport.completion(
            model="openai/gpt-5",
            messages=[{"role": "user", "content": "hi"}],
            api_surface="responses",
            wire_protocol="openai_responses",
        )
        assert captured[1]["model"] == "openai/responses/gpt-5"
        assert "api_surface" not in captured[1]
        assert "wire_protocol" not in captured[1]

        # Router creation encodes both model_info.dsa_api_surface and litellm_params.api_surface.
        router = transport.create_router(
            [
                {
                    "model_name": "relay-resp",
                    "litellm_params": {
                        "model": "openai/gpt-5",
                        "api_surface": "responses",
                        "wire_protocol": "openai_responses",
                    },
                },
                {
                    "model_name": "yaml-resp",
                    "litellm_params": {"model": "openai/gpt-5.6-sol"},
                    "model_info": {"dsa_api_surface": "responses"},
                },
            ],
            routing_strategy="simple-shuffle",
            num_retries=2,
        )
        assert router_init_lists[0][0]["litellm_params"] == {"model": "openai/responses/gpt-5"}
        assert router_init_lists[0][1]["litellm_params"] == {"model": "openai/responses/gpt-5.6-sol"}

        # Prebuilt SDK router dispatch also strips internal api_surface/wire_protocol.
        assert (
            dispatch_completion(
                router=router,
                model="yaml-resp",
                messages=[{"role": "user", "content": "hi"}],
                api_surface="responses",
                wire_protocol="openai_responses",
            )
            == "from-sdk-router"
        )
        assert router_comp_calls == [
            {"model": "yaml-resp", "messages": [{"role": "user", "content": "hi"}]}
        ]

        assert transport.can_register_model() is True
        transport.register_model({"x": {"max_tokens": 100}})
        fake_litellm.register_model.assert_called_once_with({"x": {"max_tokens": 100}})
        assert transport.get_model_cost() == {"gpt-4o": {"input_cost_per_token": 0.1}}
        assert transport.estimate_tokens("hello", model="openai/gpt-4o") == 19

        transport.silence_logs()
        assert fake_litellm.set_verbose is False
        assert fake_litellm.suppress_debug_info is True
        assert fake_litellm.disable_streaming_logging is True
        assert logging.getLogger("litellm").level == logging.WARNING


def test_cjk_aware_token_estimation_and_zero_return_fallback() -> None:
    """Token fallback preserves ceil(len/3) for ASCII, scales CJK, and catches 0-returning tokenizers."""
    assert estimate_tokens_fallback("") == 0
    assert estimate_tokens_fallback("abcdefg") == math.ceil(7 / 3)
    cjk_text = "贵州茅台业绩分析与风险评估"
    cjk_est = estimate_tokens_fallback(cjk_text)
    assert cjk_est == math.ceil(len(cjk_text) * 1.5)
    assert cjk_est > math.ceil(len(cjk_text) / 3) * 3

    broken_litellm = SimpleNamespace(
        token_counter=MagicMock(side_effect=RuntimeError("tokenizer offline"))
    )
    with patch.dict(sys.modules, {"litellm": broken_litellm}, clear=False):
        assert estimate_tokens("", model="openai/gpt-4o") == 0
        assert estimate_tokens(cjk_text, model="openai/gpt-4o") == cjk_est
        assert estimate_tokens("abcdefg", model="openai/gpt-4o") == math.ceil(7 / 3)

    # Disabled/stub tokenizer returning 0 for non-empty text must fall back to heuristic.
    zero_litellm = SimpleNamespace(token_counter=MagicMock(return_value=0))
    with patch.dict(sys.modules, {"litellm": zero_litellm}, clear=False):
        assert estimate_tokens("", model="openai/gpt-4o") == 0
        assert estimate_tokens(cjk_text, model="openai/gpt-4o") == cjk_est
        assert estimate_tokens("abcdefg", model="openai/gpt-4o") == math.ceil(7 / 3)


def test_contextvar_transport_isolation_across_threads_and_async() -> None:
    """use_transport() isolates concurrent threads and asyncio tasks cleanly."""
    t_a = _RecordingTransport(response_text="from-a")
    t_b = _RecordingTransport(response_text="from-b")
    barrier = threading.Barrier(2)
    results: Dict[str, str] = {}

    def _worker(label: str, transport: _RecordingTransport) -> None:
        with use_transport(transport):
            barrier.wait(timeout=5)
            resp = dispatch_completion(model="openai/gpt-4o", messages=[])
            results[label] = resp.choices[0].message.content

    thread_a = threading.Thread(target=_worker, args=("a", t_a))
    thread_b = threading.Thread(target=_worker, args=("b", t_b))
    thread_a.start()
    thread_b.start()
    thread_a.join(timeout=5)
    thread_b.join(timeout=5)
    assert results == {"a": "from-a", "b": "from-b"}
    assert len(t_a.completion_calls) == 1
    assert len(t_b.completion_calls) == 1

    async def _run_async() -> Dict[str, str]:
        async def _task(label: str, transport: _RecordingTransport) -> tuple[str, str]:
            with use_transport(transport):
                await asyncio.sleep(0.01)
                resp = dispatch_completion(model="openai/gpt-4o", messages=[])
                return label, resp.choices[0].message.content

        pairs = await asyncio.gather(_task("a", t_a), _task("b", t_b))
        return dict(pairs)

    assert asyncio.run(_run_async()) == {"a": "from-a", "b": "from-b"}


def test_set_default_transport_invalidates_provider_and_pricing_caches() -> None:
    """Changing the process-wide default transport clears provider and fallback pricing caches."""
    custom = _RecordingTransport()
    custom.providers = frozenset({"openai", "custom-default-provider"})
    try:
        set_default_transport(custom)
        assert "custom-default-provider" in get_litellm_model_providers()

        custom2 = _RecordingTransport()
        custom2.providers = frozenset({"openai", "second-default-provider"})
        set_default_transport(custom2)
        providers2 = get_litellm_model_providers()
        assert "second-default-provider" in providers2
        assert "custom-default-provider" not in providers2
    finally:
        set_default_transport(None)


def test_litellm_compat_proxy_backward_compatibility() -> None:
    """LiteLLMPatchProxy supports legacy module.litellm.<attr> test monkey-patching."""
    proxy = create_litellm_compat_proxy(disable_streaming_logging=True)
    assert isinstance(proxy, LiteLLMPatchProxy)
    assert proxy.disable_streaming_logging is True

    mock_comp = MagicMock(return_value="patched-response")
    mock_reg = MagicMock()
    proxy.completion = mock_comp
    proxy.register_model = mock_reg
    proxy.model_cost = {"custom-m": {"max_tokens": 4096}}

    class _FakeRateLimit(Exception):
        pass

    proxy.RateLimitError = _FakeRateLimit

    assert dispatch_completion(compat_proxy=proxy, model="openai/gpt-4o") == "patched-response"
    mock_comp.assert_called_once_with(model="openai/gpt-4o")
    assert can_register_model(compat_proxy=proxy) is True
    register_model({"m2": {}}, compat_proxy=proxy)
    mock_reg.assert_called_once_with({"m2": {}})
    assert get_model_cost(compat_proxy=proxy) == {"custom-m": {"max_tokens": 4096}}

    fake_litellm = SimpleNamespace(RateLimitError=RuntimeError)
    with patch.dict(sys.modules, {"litellm": fake_litellm}, clear=False):
        exc_types = resolve_exception_types("RateLimitError", compat_proxy=proxy)
        assert _FakeRateLimit in exc_types
        assert RuntimeError in exc_types

    # ContextVar use_transport override takes precedence over compat_proxy.
    fake = _RecordingTransport(response_text="override-wins")
    with use_transport(fake):
        resp = dispatch_completion(compat_proxy=proxy, model="openai/gpt-4o")
        assert resp.choices[0].message.content == "override-wins"


def test_deployment_spec_normalization_separation_single_pass_and_redacted_repr(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DeploymentSpec separates protocols, filters non-generation defaults, resolves env once, and hides secrets in repr."""
    monkeypatch.setenv("TEST_RELAY_KEY", "sk-resolved-secret")
    monkeypatch.setenv("TEST_RELAY_BASE", "https://relay.example.com/v1")
    # Value intentionally starts with os.environ/ to prove single-pass resolution.
    monkeypatch.setenv("TEST_AUTH_HEADER", "os.environ/SHOULD_NOT_REEXPAND")
    monkeypatch.setenv("SHOULD_NOT_REEXPAND", "CORRUPTED")
    monkeypatch.delenv("TEST_MISSING_ENV", raising=False)

    assert find_unresolved_env_var("os.environ/TEST_MISSING_ENV") == "TEST_MISSING_ENV"
    assert find_unresolved_env_var("os.environ/TEST_RELAY_KEY") is None

    raw_entry = {
        "model_name": "relay-gpt5",
        "litellm_params": {
            "model": "openai/gpt-5",
            "api_key": "os.environ/TEST_RELAY_KEY",
            "base_url": "os.environ/TEST_RELAY_BASE",
            "wire_protocol": "openai_chat",
            "custom_llm_provider": "openai",
            "extra_headers": {
                "Authorization": "os.environ/TEST_AUTH_HEADER",
                "X-Tenant": "dsa",
            },
            "extra_body": {"nested": {"flag": True}},
            "temperature": 0.3,
            "max_tokens": 4096,
            "store": False,
            "timeout": "45.5",
            "order": 2,
            # Router-only, cloud IAM, & unlisted credential keys MUST NOT leak into request_defaults.
            "rpm": 100,
            "tpm": 100000,
            "num_retries": 3,
            "drop_params": True,
            "api_version": "2025-01-01",
            "aws_region_name": "us-east-1",
            "vertex_project": "proj-1",
            "azure_ad_token": "tok",
            "token": "secret-token-value",
            "litellm_credential_name": "cred-name",
            "max_budget": 10.0,
        },
        "model_info": {
            "dsa_api_surface": "chat_completions",
            "dsa_channel_protocol": "openai",
        },
    }

    assert resolve_env_reference("os.environ/TEST_RELAY_KEY") == "sk-resolved-secret"
    resolved_params = resolve_litellm_params_env(raw_entry["litellm_params"])
    assert resolved_params["api_key"] == "sk-resolved-secret"
    # Deep copy check: mutating nested extra_body must not mutate raw_entry.
    resolved_params["extra_body"]["nested"]["flag"] = False
    assert raw_entry["litellm_params"]["extra_body"]["nested"]["flag"] is True
    assert raw_entry["litellm_params"]["api_key"] == "os.environ/TEST_RELAY_KEY"

    spec = normalize_deployment_spec(raw_entry)
    assert isinstance(spec, DeploymentSpec)
    assert spec.alias == "relay-gpt5"
    assert spec.wire_model == "openai/gpt-5"
    assert spec.channel_protocol == "openai"
    assert spec.wire_protocol == "openai_chat"
    assert spec.custom_llm_provider == "openai"
    assert spec.api_surface == "chat_completions"
    assert spec.api_base == "https://relay.example.com/v1"
    assert spec.api_key == "sk-resolved-secret"
    # Single-pass resolution preserved literal os.environ/ value without second expansion.
    assert spec.extra_headers == {
        "Authorization": "os.environ/SHOULD_NOT_REEXPAND",
        "X-Tenant": "dsa",
    }
    assert spec.request_defaults == {"temperature": 0.3, "max_tokens": 4096, "store": False}
    assert spec.priority == 2
    assert spec.timeout == 45.5
    # Secret fields omitted from repr().
    rendered = repr(spec)
    assert "sk-resolved-secret" not in rendered
    assert "SHOULD_NOT_REEXPAND" not in rendered
    assert "secret-token-value" not in rendered
    assert "cred-name" not in rendered

    # Explicit base_url="" overrides api_base to match LiteLLM 1.98.1 precedence.
    empty_override_spec = normalize_deployment_spec(
        {
            "model_name": "override-empty",
            "litellm_params": {
                "model": "openai/gpt-5",
                "api_base": "https://relay.example.com/v1",
                "base_url": "",
            },
        }
    )
    assert empty_override_spec.api_base == ""

    # Default priority without explicit order/priority stays 0 across sibling entries.
    plain_entry = {"model_name": "m", "litellm_params": {"model": "openai/m"}}
    specs = normalize_deployment_specs([plain_entry, plain_entry])
    assert [item.priority for item in specs] == [0, 0]

    normalized_entries = normalize_model_list_entries([raw_entry])
    assert normalized_entries[0]["litellm_params"]["api_key"] == "sk-resolved-secret"
    assert normalized_entries[0]["model_info"]["dsa_api_surface"] == "chat_completions"


def test_ranker_yaml_and_direct_attempt_header_host_binding(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ranker resolves YAML env refs, preserves surface, and refuses to bind channel headers to outer host/key."""
    monkeypatch.setenv("SCREENING_YAML_KEY", "sk-yaml-resolved-key")
    monkeypatch.setenv("SCREENING_YAML_BASE", "https://yaml-relay.example/v1")
    monkeypatch.setenv("SCREENING_YAML_HEADER", "Bearer yaml-hdr-token")

    yaml_path = tmp_path / "litellm.yaml"
    yaml_path.write_text(
        """
model_list:
  - model_name: openai/gpt-5
    litellm_params:
      model: openai/gpt-5
      api_key: os.environ/SCREENING_YAML_KEY
      api_base: os.environ/SCREENING_YAML_BASE
      extra_headers:
        Authorization: os.environ/SCREENING_YAML_HEADER
    model_info:
      dsa_api_surface: chat_completions
      dsa_channel_protocol: openai
""".strip(),
        encoding="utf-8",
    )

    fake = _RecordingTransport(response_text='{"ranked": []}')
    with use_transport(fake):
        out = ranker._call_llm(
            "rank stocks",
            api_key="",
            model="openai/gpt-5",
            base_url="",
            config_path=str(yaml_path),
            json_mode=False,
        )

    assert out == '{"ranked": []}'
    assert len(fake.router_calls) == 1
    entry = fake.router_calls[0]["model_list"][0]
    assert entry["litellm_params"]["api_key"] == "sk-yaml-resolved-key"
    assert entry["litellm_params"]["api_base"] == "https://yaml-relay.example/v1"
    assert entry["litellm_params"]["extra_headers"]["Authorization"] == "Bearer yaml-hdr-token"
    assert entry["model_info"]["dsa_api_surface"] == "chat_completions"

    # P0-2: channel omitting base_url inherits outer base_url -> MUST NOT attach channel extra_headers!
    attempts_outer_base = ranker._build_litellm_attempts(
        "openai/gpt-5",
        api_key="sk-outer",
        base_url="https://outer-host.example/v1",
        channels=[
            {
                "name": "header-channel",
                "protocol": "openai",
                "api_surface": "chat_completions",
                "api_keys": ["sk-channel"],
                "base_url": "",
                "models": ["openai/gpt-5"],
                "extra_headers": {"Authorization": "Bearer private-channel-secret"},
            }
        ],
    )
    assert len(attempts_outer_base) == 1
    assert attempts_outer_base[0]["api_base"] == "https://outer-host.example/v1"
    assert "extra_headers" not in attempts_outer_base[0]

    # P0-2: channel omitting api_keys inherits outer api_key -> MUST NOT attach channel extra_headers!
    attempts_outer_key = ranker._build_litellm_attempts(
        "openai/gpt-5",
        api_key="sk-outer",
        base_url="",
        channels=[
            {
                "name": "header-channel",
                "protocol": "openai",
                "api_surface": "chat_completions",
                "api_keys": [],
                "base_url": "https://channel-host.example/v1",
                "models": ["openai/gpt-5"],
                "extra_headers": {"Authorization": "Bearer private-channel-secret"},
            }
        ],
    )
    assert len(attempts_outer_key) == 1
    assert attempts_outer_key[0]["api_key"] == "sk-outer"
    assert "extra_headers" not in attempts_outer_key[0]

    # When channel owns BOTH base_url and api_keys, headers and api_surface ARE preserved,
    # and _unique_attempts distinguishes attempts with different extra_headers.
    attempts_owned = ranker._build_litellm_attempts(
        "openai/gpt-5",
        api_key="",
        base_url="",
        channels=[
            {
                "name": "relay-1",
                "protocol": "openai",
                "api_surface": "chat_completions",
                "api_keys": ["sk-shared"],
                "base_url": "https://relay.example/v1",
                "models": ["openai/gpt-5"],
                "extra_headers": {"X-Route": "a"},
            },
            {
                "name": "relay-2",
                "protocol": "openai",
                "api_surface": "chat_completions",
                "api_keys": ["sk-shared"],
                "base_url": "https://relay.example/v1",
                "models": ["openai/gpt-5"],
                "extra_headers": {"X-Route": "b"},
            },
        ],
    )
    assert len(attempts_owned) == 2
    assert attempts_owned[0]["api_surface"] == "chat_completions"
    assert [a["extra_headers"] for a in attempts_owned] == [{"X-Route": "a"}, {"X-Route": "b"}]


def test_screening_header_proxy_isolation_precedence_ambiguity_and_nesting() -> None:
    """Screening header proxy closes cross-host, api_base/base_url conflict, case-dup, ambiguity, and nesting leaks."""
    cfg = Config(
        litellm_model="openai/gpt-4o-mini",
        llm_model_list=[
            {
                "model_name": "openai/gpt-4o-mini",
                "litellm_params": {
                    "model": "openai/gpt-4o-mini",
                    "api_key": "sk-relay-a",
                    "api_base": "https://relay-a.example/v1/",
                    "extra_headers": {
                        "Authorization": "Bearer relay-a-secret",
                        "X-Tenant": "relay-a",
                    },
                },
            }
        ],
    )

    fake = _RecordingTransport(response_text="ok")
    with use_transport(fake):
        with screening_service._screening_litellm_headers(cfg):
            # 1. Omitted api_base -> MUST NOT inherit relay headers.
            dispatch_completion(model="openai/gpt-4o-mini", api_key="sk-relay-a", messages=[])
            # 2. Omitted api_key -> MUST NOT inherit relay headers.
            dispatch_completion(
                model="openai/gpt-4o-mini",
                api_base="https://relay-a.example/v1",
                messages=[],
            )
            # 3. P0-1: conflicting api_base vs base_url -> MUST NOT inject headers!
            dispatch_completion(
                model="openai/gpt-4o-mini",
                api_key="sk-relay-a",
                api_base="https://relay-a.example/v1",
                base_url="https://attacker.example/v1",
                messages=[],
            )
            # 4. Exact host + key match with lowercase existing "authorization" -> case-insensitive override without dup!
            dispatch_completion(
                model="openai/gpt-4o-mini",
                api_key="sk-relay-a",
                api_base="https://relay-a.example/v1",
                extra_headers={"authorization": "Bearer caller-wins"},
                messages=[],
            )
            # 5. P1-3: Nested empty-header config MUST NOT inherit outer scope headers!
            empty_cfg = Config(litellm_model="openai/gpt-4o-mini", llm_model_list=[])
            with screening_service._screening_litellm_headers(empty_cfg):
                dispatch_completion(
                    model="openai/gpt-4o-mini",
                    api_key="sk-relay-a",
                    api_base="https://relay-a.example/v1",
                    messages=[],
                )
            # 6. P1-3: Nested distinct-header config replaces outer proxy without accumulating outer headers!
            inner_cfg = Config(
                litellm_model="openai/gpt-4o-mini",
                llm_model_list=[
                    {
                        "model_name": "openai/gpt-4o-mini",
                        "litellm_params": {
                            "model": "openai/gpt-4o-mini",
                            "api_key": "sk-relay-a",
                            "api_base": "https://relay-a.example/v1",
                            "extra_headers": {"X-Inner": "only"},
                        },
                    }
                ],
            )
            with screening_service._screening_litellm_headers(inner_cfg):
                dispatch_completion(
                    model="openai/gpt-4o-mini",
                    api_key="sk-relay-a",
                    api_base="https://relay-a.example/v1",
                    messages=[],
                )

    assert "extra_headers" not in fake.completion_calls[0]
    assert "extra_headers" not in fake.completion_calls[1]
    assert "extra_headers" not in fake.completion_calls[2]
    assert fake.completion_calls[3]["extra_headers"] == {
        "X-Tenant": "relay-a",
        "authorization": "Bearer caller-wins",
    }
    assert "extra_headers" not in fake.completion_calls[4]
    assert fake.completion_calls[5]["extra_headers"] == {"X-Inner": "only"}

    # P1-2: Ambiguous same-host/same-key routes with conflicting headers decline injection.
    ambiguous_cfg = Config(
        litellm_model="openai/gpt-4o-mini",
        llm_model_list=[
            {
                "model_name": "openai/gpt-4o-mini",
                "litellm_params": {
                    "model": "openai/gpt-4o-mini",
                    "api_key": "sk-same",
                    "api_base": "https://same.example/v1",
                    "extra_headers": {"X-Tenant": "tenant-1"},
                },
            },
            {
                "model_name": "openai/gpt-4o-mini",
                "litellm_params": {
                    "model": "openai/gpt-4o-mini",
                    "api_key": "sk-same",
                    "api_base": "https://same.example/v1",
                    "extra_headers": {"X-Tenant": "tenant-2"},
                },
            },
        ],
    )
    fake_amb = _RecordingTransport(response_text="ok")
    with use_transport(fake_amb):
        with screening_service._screening_litellm_headers(ambiguous_cfg):
            dispatch_completion(
                model="openai/gpt-4o-mini",
                api_key="sk-same",
                api_base="https://same.example/v1",
                messages=[],
            )
    assert "extra_headers" not in fake_amb.completion_calls[0]


def test_vision_extractor_honors_base_url_surface_and_fails_closed_on_missing_env_base(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Vision honors YAML base_url + dsa_api_surface and fails closed if os.environ/ endpoint is unset."""
    cfg_chat = Config(
        vision_model="openai/gpt-5",
        llm_model_list=[
            {
                "model_name": "openai/gpt-5",
                "litellm_params": {
                    "model": "openai/gpt-5",
                    "api_key": "sk-vision-key-1234",
                    "base_url": "https://vision-relay.example/v1",
                },
                "model_info": {"dsa_api_surface": "chat_completions"},
            }
        ],
    )
    fake = _RecordingTransport(response_text='[{"code":"600519","name":"贵州茅台","confidence":"high"}]')
    monkeypatch.setattr(image_stock_extractor, "get_config", lambda: cfg_chat)
    with use_transport(fake):
        out = image_stock_extractor._call_litellm_vision("aGVsbG8=", "image/png")

    assert "600519" in out
    assert fake.completion_calls[0]["model"] == "openai/gpt-5"
    assert fake.completion_calls[0]["api_base"] == "https://vision-relay.example/v1"
    assert fake.completion_calls[0]["api_surface"] == "chat_completions"

    # Responses surface from YAML model_info encodes wire model & forwards api_surface=responses.
    cfg_resp = Config(
        vision_model="openai/gpt-5",
        llm_model_list=[
            {
                "model_name": "openai/gpt-5",
                "litellm_params": {
                    "model": "openai/gpt-5",
                    "base_url": "http://127.0.0.1:8642/v1",
                },
                "model_info": {"dsa_api_surface": "responses"},
            }
        ],
    )
    fake_resp = _RecordingTransport(response_text="[]")
    monkeypatch.setattr(image_stock_extractor, "get_config", lambda: cfg_resp)
    with use_transport(fake_resp):
        image_stock_extractor._call_litellm_vision("aGVsbG8=", "image/png")

    assert fake_resp.completion_calls[0]["model"] == "openai/responses/gpt-5"
    assert fake_resp.completion_calls[0]["api_base"] == "http://127.0.0.1:8642/v1"
    assert fake_resp.completion_calls[0]["api_surface"] == "responses"

    # P0-3: Unset os.environ/MISSING_VISION_BASE MUST fail closed without dispatching key/image!
    monkeypatch.delenv("MISSING_VISION_BASE", raising=False)
    cfg_missing_env = Config(
        vision_model="openai/gpt-5",
        llm_model_list=[
            {
                "model_name": "openai/gpt-5",
                "litellm_params": {
                    "model": "openai/gpt-5",
                    "api_key": "sk-vision-secret-key",
                    "api_base": "os.environ/MISSING_VISION_BASE",
                    "extra_headers": {"Authorization": "Bearer relay-vision-secret"},
                },
            }
        ],
    )
    fake_blocked = _RecordingTransport(response_text="[]")
    monkeypatch.setattr(image_stock_extractor, "get_config", lambda: cfg_missing_env)
    with use_transport(fake_blocked):
        with pytest.raises(ValueError, match="MISSING_VISION_BASE"):
            image_stock_extractor._call_litellm_vision("aGVsbG8=", "image/png")
    assert fake_blocked.completion_calls == []


def test_config_persists_dsa_api_surface_protocol_and_preserves_relay_models() -> None:
    """Config persists dsa_api_surface on OpenAI channels, avoids mislabeling explicit anthropic/, and keeps relay IDs."""
    env = {
        "LLM_CHANNELS": "chat_relay,resp_relay,claude_direct,mixed_openai",
        "LLM_CHAT_RELAY_PROTOCOL": "openai",
        "LLM_CHAT_RELAY_API_SURFACE": "chat_completions",
        "LLM_CHAT_RELAY_BASE_URL": "https://api.siliconflow.cn/v1",
        "LLM_CHAT_RELAY_API_KEY": "sk-chat-relay-1234",
        "LLM_CHAT_RELAY_MODELS": "gpt-5,Qwen/Qwen3-235B-A22B,deepseek-ai/DeepSeek-V3.2",
        "LLM_RESP_RELAY_PROTOCOL": "openai",
        "LLM_RESP_RELAY_API_SURFACE": "responses",
        "LLM_RESP_RELAY_BASE_URL": "https://responses.example/v1",
        "LLM_RESP_RELAY_API_KEY": "sk-resp-relay-1234",
        "LLM_RESP_RELAY_MODELS": "gpt-5.6-sol",
        "LLM_CLAUDE_DIRECT_PROTOCOL": "anthropic",
        "LLM_CLAUDE_DIRECT_API_KEY": "sk-ant-direct-1234",
        "LLM_CLAUDE_DIRECT_MODELS": "claude-sonnet-4-6",
        "LLM_MIXED_OPENAI_PROTOCOL": "openai",
        "LLM_MIXED_OPENAI_BASE_URL": "https://api.example.com/v1",
        "LLM_MIXED_OPENAI_API_KEY": "sk-mixed-1234",
        "LLM_MIXED_OPENAI_MODELS": "anthropic/claude-opus-4-6",
    }
    with (
        patch("src.config.setup_env"),
        patch.object(Config, "_parse_litellm_yaml", return_value=[]),
        patch.dict(os.environ, env, clear=True),
    ):
        cfg = Config._load_from_env()

    by_alias = {entry["model_name"]: entry for entry in cfg.llm_model_list}
    assert by_alias["openai/gpt-5"]["model_info"] == {
        "dsa_channel_protocol": "openai",
        "dsa_api_surface": "chat_completions",
    }
    assert by_alias["openai/Qwen/Qwen3-235B-A22B"]["litellm_params"]["model"] == "openai/Qwen/Qwen3-235B-A22B"
    assert by_alias["openai/Qwen/Qwen3-235B-A22B"]["model_info"]["dsa_api_surface"] == "chat_completions"
    assert (
        by_alias["openai/deepseek-ai/DeepSeek-V3.2"]["litellm_params"]["model"]
        == "openai/deepseek-ai/DeepSeek-V3.2"
    )
    assert by_alias["openai/gpt-5.6-sol"]["litellm_params"]["model"] == "openai/responses/gpt-5.6-sol"
    assert by_alias["openai/gpt-5.6-sol"]["model_info"] == {
        "dsa_channel_protocol": "openai",
        "dsa_api_surface": "responses",
    }
    # Non-OpenAI direct channel and explicit anthropic/ on generic host do NOT claim OpenAI protocol/surface.
    assert by_alias["anthropic/claude-sonnet-4-6"]["model_info"] == {
        "dsa_channel_protocol": "anthropic",
    }
    assert by_alias["anthropic/claude-opus-4-6"]["model_info"] == {
        "dsa_channel_protocol": "anthropic",
    }

    assert (
        normalize_llm_channel_model("Qwen/Qwen3-235B-A22B", "openai", "https://api.siliconflow.cn/v1")
        == "openai/Qwen/Qwen3-235B-A22B"
    )
    assert (
        normalize_llm_channel_model("deepseek-ai/DeepSeek-V3.2", "openai", "https://api.siliconflow.cn/v1")
        == "openai/deepseek-ai/DeepSeek-V3.2"
    )
    assert (
        normalize_llm_channel_model("anthropic/claude-sonnet-4-6", "openai", "https://router.requesty.ai/v1")
        == "openai/anthropic/claude-sonnet-4-6"
    )
    assert (
        normalize_llm_channel_model("openai/anthropic/claude-sonnet-4-6", "openai", "https://oneapi.example/v1")
        == "openai/anthropic/claude-sonnet-4-6"
    )
    assert (
        normalize_llm_channel_model("anthropic/claude-sonnet-4-6", "openai", "https://api.example.com/v1")
        == "anthropic/claude-sonnet-4-6"
    )


def test_system_config_test_llm_channel_redaction_hermes_guard_and_cache_reset() -> None:
    """test_llm_channel forwards surface+headers, redacts bare/custom/truncated secrets, blocks Hermes headers, resets cache."""
    service = SystemConfigService()
    fake = _RecordingTransport(response_text='{"status":"ok"}')

    with use_transport(fake):
        payload = service.test_llm_channel(
            name="relay",
            protocol="openai",
            api_surface="chat_completions",
            base_url="https://relay.example/v1",
            api_key="sk-test-channel-key",
            models=["gpt-5"],
            capability_checks=["json", "tools", "stream", "vision"],
            extra_headers={"X-Custom-Tenant": "acme", "Authorization": "Bearer custom-hdr-secret"},
        )

    assert payload["success"] is True
    assert payload["resolved_api_surface"] == "chat_completions"
    assert len(fake.completion_calls) == 5
    for call in fake.completion_calls:
        assert call["api_surface"] == "chat_completions"
        assert call["extra_headers"] == {
            "X-Custom-Tenant": "acme",
            "Authorization": "Bearer custom-hdr-secret",
        }
    assert all(res["status"] == "passed" for res in payload["capability_results"].values())

    # P0-4: Bare Bearer token, custom auth header, capability failure, and mid-secret [:80] truncation are all redacted!
    class _SecretEchoTransport(_RecordingTransport):
        def completion(self, **kwargs: Any) -> Any:
            if kwargs.get("response_format"):
                raise RuntimeError(
                    "Capability failed: bare token bare-tok-9999 and relay-custom-secret-7777 rejected"
                )
            # Echo secret crossing the 80-char preview truncation boundary.
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content=("A" * 72) + "bare-tok-9999-and-relay-custom-secret-7777",
                            tool_calls=None,
                        )
                    )
                ]
            )

    with use_transport(_SecretEchoTransport()):
        echo_payload = service.test_llm_channel(
            name="relay",
            protocol="openai",
            api_surface="chat_completions",
            base_url="https://relay.example/v1",
            api_key="sk-test-channel-key",
            models=["gpt-5"],
            capability_checks=["json"],
            extra_headers={
                "Authorization": "Bearer bare-tok-9999",
                "X-Relay-Token": "relay-custom-secret-7777",
            },
        )
    serialized = str(echo_payload)
    assert "bare-tok" not in serialized
    assert "relay-custom-secret" not in serialized

    # P1-1: Reserved Hermes channel rejects non-empty extra_headers before opening any client.
    fake_hermes = _RecordingTransport(response_text="OK")
    with use_transport(fake_hermes):
        hermes_payload = service.test_llm_channel(
            name="hermes",
            protocol="openai",
            api_surface="chat_completions",
            base_url="http://127.0.0.1:8642/v1",
            api_key="sk-hermes-valid-key",
            models=["hermes-agent"],
            extra_headers={"X-Relay-Token": "secret-val"},
        )
    assert hermes_payload["success"] is False
    assert hermes_payload["error_code"] == "invalid_config"
    assert hermes_payload["details"]["issue_code"] == "unsupported_extra_headers"
    assert fake_hermes.completion_calls == []

    # _reload_runtime_singletons() resets cached transport singleton.
    set_default_transport(None)
    reset_transport_cache()
    first = get_transport()
    assert get_transport() is first
    SystemConfigService._reload_runtime_singletons()
    second = get_transport()
    assert second is not first


def test_use_transport_intercepts_all_runtime_entry_points(monkeypatch: pytest.MonkeyPatch) -> None:
    """End-to-end verification that use_transport() intercepts analyzer, adapter, chat_context, and providers."""
    fake = _RecordingTransport(response_text='{"status":"ok"}')
    cfg = Config(agent_litellm_model="openai/gpt-4o", litellm_model="openai/gpt-4o")

    with use_transport(fake):
        assert "custom-transport" in get_model_providers()
        assert "custom-transport" in get_litellm_model_providers()
        assert chat_context.estimate_text_tokens("hello", cfg) == 42

        silence_litellm_logs()
        assert fake.silence_calls == 1

        analyzer = GeminiAnalyzer.__new__(GeminiAnalyzer)
        analyzer._router = None
        analyzer._get_runtime_config = lambda: cfg  # type: ignore[method-assign]
        monkeypatch.setattr("src.analyzer.get_api_keys_for_model", lambda m, c: ["sk-test-123456"])
        analyzer._dispatch_litellm_completion(
            "openai/gpt-4o",
            {"model": "openai/gpt-4o", "messages": [{"role": "user", "content": "hi"}]},
            config=cfg,
            use_channel_router=False,
            router_model_names=set(),
        )

        register_fallback_model_pricing(["openai/custom-test-model"])
        adapter = LLMToolAdapter.__new__(LLMToolAdapter)
        adapter._config = cfg
        adapter._router = None
        adapter._router_has_merged_extra_body = False
        adapter._legacy_router_model_list = []
        adapter._route_resolution = SimpleNamespace(primary_model="openai/gpt-4o", model_list=[])
        adapter._has_channel_config = lambda: False  # type: ignore[method-assign]
        monkeypatch.setattr("src.agent.llm_adapter.get_api_keys_for_model", lambda m, c: ["sk-test-123456"])
        adapter._call_litellm_model(
            [{"role": "user", "content": "ping"}],
            [],
            "openai/gpt-4o",
        )

    assert len(fake.completion_calls) >= 2
    assert len(fake.pricing_calls) >= 1


def test_codex_round2_regressions_keyless_yaml_vision_screening_redaction_and_router(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Regression coverage for keyless local channels, YAML unresolved endpoints, single-pass env, screening ambiguity, redaction, and prebuilt routers."""
    # 1. P0-1: Explicit keyless local/Ollama channel (api_keys=[""]) MUST NOT inherit outer_api_key.
    keyless_attempts = ranker._build_litellm_attempts(
        "ollama/qwen3:8b",
        api_key="sk-outer-secret-key",
        base_url="",
        channels=[
            {
                "name": "local-ollama",
                "protocol": "ollama",
                "api_surface": "",
                "api_keys": [""],
                "base_url": "http://127.0.0.1:11434/v1",
                "models": ["ollama/qwen3:8b"],
                "extra_headers": {"X-Local-Tag": "ollama"},
            }
        ],
    )
    assert len(keyless_attempts) == 1
    assert "api_key" not in keyless_attempts[0]
    assert keyless_attempts[0]["api_base"] == "http://127.0.0.1:11434/v1"
    assert keyless_attempts[0]["extra_headers"] == {"X-Local-Tag": "ollama"}

    # 2. P0-2: Config._parse_litellm_yaml preserves unresolved endpoint env error end-to-end into Vision,
    # even when the deployment is keyless or legacy openai_api_keys is set!
    monkeypatch.delenv("MISSING_VISION_YAML_URL", raising=False)
    broken_vision_yaml = tmp_path / "broken_vision.yaml"
    broken_vision_yaml.write_text(
        """
model_list:
  - model_name: openai/gpt-5
    litellm_params:
      model: openai/gpt-5
      api_base: os.environ/MISSING_VISION_YAML_URL
""".strip(),
        encoding="utf-8",
    )
    parsed_broken = Config._parse_litellm_yaml(str(broken_vision_yaml))
    assert parsed_broken[0]["model_info"]["_dsa_unresolved_endpoint_env"] == "api_base:MISSING_VISION_YAML_URL"

    cfg_broken_vision = Config(
        vision_model="openai/gpt-5",
        openai_api_keys=["sk-legacy-fallback-1234"],
        llm_model_list=parsed_broken,
    )
    fake_vision = _RecordingTransport(response_text="[]")
    monkeypatch.setattr(image_stock_extractor, "get_config", lambda: cfg_broken_vision)
    with use_transport(fake_vision):
        with pytest.raises(ValueError, match="MISSING_VISION_YAML_URL"):
            image_stock_extractor._call_litellm_vision("aGVsbG8=", "image/png")
    assert fake_vision.completion_calls == []

    # 3. P0-3 + P1-3: Vision rejects explicit base_url="" alongside api_base AND case-sensitive path mismatch,
    # while accepting scheme/host case differences.
    cfg_empty_base = Config(
        vision_model="openai/gpt-5",
        llm_model_list=[
            {
                "model_name": "openai/gpt-5",
                "litellm_params": {
                    "model": "openai/gpt-5",
                    "api_key": "sk-vision-key-1234",
                    "api_base": "https://relay.example/v1",
                    "base_url": "",
                },
            }
        ],
    )
    monkeypatch.setattr(image_stock_extractor, "get_config", lambda: cfg_empty_base)
    with use_transport(fake_vision):
        with pytest.raises(ValueError, match="conflicting api_base and base_url"):
            image_stock_extractor._call_litellm_vision("aGVsbG8=", "image/png")

    cfg_case_path_conflict = Config(
        vision_model="openai/gpt-5",
        llm_model_list=[
            {
                "model_name": "openai/gpt-5",
                "litellm_params": {
                    "model": "openai/gpt-5",
                    "api_key": "sk-vision-key-1234",
                    "api_base": "https://relay.example/V1/CaseA",
                    "base_url": "https://relay.example/v1/casea",
                },
            }
        ],
    )
    monkeypatch.setattr(image_stock_extractor, "get_config", lambda: cfg_case_path_conflict)
    with use_transport(fake_vision):
        with pytest.raises(ValueError, match="conflicting api_base and base_url"):
            image_stock_extractor._call_litellm_vision("aGVsbG8=", "image/png")

    cfg_host_case_ok = Config(
        vision_model="openai/gpt-5",
        llm_model_list=[
            {
                "model_name": "openai/gpt-5",
                "litellm_params": {
                    "model": "openai/gpt-5",
                    "api_key": "sk-vision-key-1234",
                    "api_base": "HTTPS://RELAY.EXAMPLE/v1/CaseA/",
                    "base_url": "https://relay.example/v1/CaseA",
                },
            }
        ],
    )
    monkeypatch.setattr(image_stock_extractor, "get_config", lambda: cfg_host_case_ok)
    with use_transport(fake_vision):
        image_stock_extractor._call_litellm_vision("aGVsbG8=", "image/png")
    assert fake_vision.completion_calls[0]["api_base"] == "https://relay.example/v1/CaseA"

    # 4. P0-3 + P1-2: Screening proxy rejects explicit base_url="" override, unset os.environ/ endpoint,
    # headerless sibling ambiguity, and pre-existing case duplicates inside injected headers.
    monkeypatch.delenv("MISSING_SCREEN_BASE", raising=False)
    cfg_screen_edge = Config(
        litellm_model="openai/gpt-4o-mini",
        llm_model_list=[
            {
                "model_name": "openai/gpt-4o-mini",
                "litellm_params": {
                    "model": "openai/gpt-4o-mini",
                    "api_key": "sk-relay-a",
                    "api_base": "https://relay-a.example/v1",
                    "extra_headers": {
                        "Authorization": "Bearer first-dup",
                        "authorization": "Bearer second-dup",
                    },
                },
            }
        ],
    )
    fake_screen = _RecordingTransport(response_text="ok")
    with use_transport(fake_screen):
        with screening_service._screening_litellm_headers(cfg_screen_edge):
            # Explicit base_url="" overrides api_base -> conflict -> no header injection!
            dispatch_completion(
                model="openai/gpt-4o-mini",
                api_key="sk-relay-a",
                api_base="https://relay-a.example/v1",
                base_url="",
                messages=[],
            )
            # Unset os.environ/ endpoint -> no header injection!
            dispatch_completion(
                model="openai/gpt-4o-mini",
                api_key="sk-relay-a",
                api_base="os.environ/MISSING_SCREEN_BASE",
                messages=[],
            )
            # Valid match deduplicates case-variant route headers cleanly.
            dispatch_completion(
                model="openai/gpt-4o-mini",
                api_key="sk-relay-a",
                api_base="https://relay-a.example/v1",
                messages=[],
            )
    assert "extra_headers" not in fake_screen.completion_calls[0]
    assert "extra_headers" not in fake_screen.completion_calls[1]
    assert fake_screen.completion_calls[2]["extra_headers"] == {"authorization": "Bearer second-dup"}

    # Headerless sibling sharing (model, api_key, api_base) with a header-bearing route is ambiguous -> no injection!
    cfg_headerless_sibling = Config(
        litellm_model="openai/gpt-4o-mini",
        llm_model_list=[
            {
                "model_name": "openai/gpt-4o-mini",
                "litellm_params": {
                    "model": "openai/gpt-4o-mini",
                    "api_key": "sk-shared",
                    "api_base": "https://shared.example/v1",
                    "extra_headers": {"X-Tenant": "tenant-a"},
                },
            },
            {
                "model_name": "openai/gpt-4o-mini",
                "litellm_params": {
                    "model": "openai/gpt-4o-mini",
                    "api_key": "sk-shared",
                    "api_base": "https://shared.example/v1",
                },
            },
        ],
    )
    fake_sib = _RecordingTransport(response_text="ok")
    with use_transport(fake_sib):
        with screening_service._screening_litellm_headers(cfg_headerless_sibling):
            dispatch_completion(
                model="openai/gpt-4o-mini",
                api_key="sk-shared",
                api_base="https://shared.example/v1",
                messages=[],
            )
    assert "extra_headers" not in fake_sib.completion_calls[0]

    # 5. End-to-end keyless local channel normalization preserves api_keys=[""] from Config -> screening_service -> ranker.
    cfg_keyless_screen = Config(
        llm_channels=[
            {
                "name": "local-ollama",
                "protocol": "ollama",
                "api_surface": "",
                "base_url": "http://127.0.0.1:11434/v1",
                "api_keys": [""],
                "models": ["ollama/qwen3:8b"],
                "extra_headers": {"X-Local-Tag": "ollama"},
                "enabled": True,
            }
        ]
    )
    normalized_keyless_channels = screening_service._normalize_dsa_llm_channels(cfg_keyless_screen)
    assert len(normalized_keyless_channels) == 1
    assert normalized_keyless_channels[0]["api_keys"] == [""]
    assert screening_service._channel_keys_for_provider(normalized_keyless_channels, {"ollama"}) == []
    normalized_attempts = ranker._build_litellm_attempts(
        "ollama/qwen3:8b",
        api_key="sk-outer-must-not-leak",
        base_url="",
        channels=normalized_keyless_channels,
    )
    assert len(normalized_attempts) == 1
    assert "api_key" not in normalized_attempts[0]
    assert normalized_attempts[0]["extra_headers"] == {"X-Local-Tag": "ollama"}

    # 6. P1-4 + Opus P2-1: hyphenated "responses-api", prebuilt Router Responses guard, and non-OpenAI YAML create_router warning.
    captured_completions: List[Dict[str, Any]] = []
    captured_routers: List[List[Dict[str, Any]]] = []

    class _DummyRouter:
        def __init__(self, model_list: List[Dict[str, Any]], **kwargs: Any) -> None:
            self.model_list = model_list
            captured_routers.append(model_list)

        def completion(self, **kwargs: Any) -> Any:
            return {"ok": True, "kwargs": kwargs}

    fake_sdk = ModuleType("litellm")
    fake_sdk.completion = lambda **kw: captured_completions.append(kw) or {"ok": True}  # type: ignore[attr-defined]
    fake_sdk.Router = _DummyRouter  # type: ignore[attr-defined]
    with patch.dict(sys.modules, {"litellm": fake_sdk}, clear=False):
        transport = LiteLLMTransport()
        transport.completion(model="openai/gpt-5", api_surface="responses-api", messages=[])
        assert captured_completions[0]["model"] == "openai/responses/gpt-5"
        assert "api_surface" not in captured_completions[0]

        # Hand-written YAML with dsa_api_surface=responses on non-openai model logs warning instead of crashing Router init.
        caplog.clear()
        with caplog.at_level(logging.WARNING):
            transport.create_router(
                [
                    {
                        "model_name": "anthropic/claude-sonnet-4-6",
                        "litellm_params": {"model": "anthropic/claude-sonnet-4-6", "api_key": "sk-ant"},
                        "model_info": {"dsa_api_surface": "responses"},
                    }
                ]
            )
        assert captured_routers[0][0]["litellm_params"]["model"] == "anthropic/claude-sonnet-4-6"
        assert "Skipping Responses wire-model encoding" in caplog.text

    # Prebuilt SDK Router without Responses-encoded deployment raises ValueError on api_surface="responses".
    prebuilt_chat_router = _DummyRouter(
        model_list=[{"model_name": "openai/gpt-5", "litellm_params": {"model": "openai/gpt-5"}}]
    )
    with pytest.raises(ValueError, match="Responses API surface"):
        dispatch_completion(
            router=prebuilt_chat_router,
            model="openai/gpt-5",
            api_surface="responses",
            messages=[],
        )

    # 7. P1-1: Non-auth generic header values (e.g. X-Format: json) must NOT corrupt capability_results keys,
    # AND stream-close failure debug logs must redact auth secrets.
    class _FailingCloseStream:
        def __iter__(self):
            yield SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content="OK"))])

        def close(self) -> None:
            raise RuntimeError("close failed with bare-tok-9999 and alfa1234/beta5678")

    class _StreamCloseTransport(_RecordingTransport):
        def completion(self, **kwargs: Any) -> Any:
            if kwargs.get("stream"):
                return _FailingCloseStream()
            return super().completion(**kwargs)

    service = SystemConfigService()
    caplog.clear()
    with caplog.at_level(logging.DEBUG, logger="src.services.system_config_service"):
        with use_transport(_StreamCloseTransport(response_text='{"status":"ok"}')):
            res = service.test_llm_channel(
                name="relay",
                protocol="openai",
                api_surface="chat_completions",
                base_url="https://relay.example/v1",
                api_key="sk-test-channel-key",
                models=["gpt-5"],
                capability_checks=["json", "stream"],
                extra_headers={
                    "X-Format": "json",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                    "X-Custom-Tenant": "acme",
                    "X-Relay": "alfa1234/beta5678",
                    "Authorization": "Bearer bare-tok-9999",
                },
            )
    assert res["success"] is True
    assert "json" in res["capability_results"]
    assert res["capability_results"]["json"]["status"] == "passed"
    assert res["capability_results"]["json"]["details"]["capability"] == "json"
    assert "bare-tok-9999" not in caplog.text
    assert "alfa1234/beta5678" not in caplog.text
    assert "[REDACTED]" in caplog.text
    redactions = service._build_extra_header_redaction_values(
        {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-Format": "json",
            "X-Relay": "alfa1234/beta5678",
        }
    )
    assert "application/json" not in redactions
    assert "json" not in redactions
    assert "alfa1234/beta5678" in redactions
