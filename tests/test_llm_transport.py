# -*- coding: utf-8 -*-
"""Unit tests, integration tests, and repo-wide AST guard for the Phase 1 LLM transport facade."""

from __future__ import annotations

import ast
import asyncio
import logging
import math
import os
from pathlib import Path
import subprocess
import sys
import threading
from types import SimpleNamespace
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


def test_repo_wide_ast_guard_forbids_direct_litellm_imports_and_calls() -> None:
    """AST guard preventing direct litellm imports/loads/SDK calls outside src/llm/transport.py."""
    forbidden_litellm_attrs = {
        "completion",
        "acompletion",
        "Router",
        "register_model",
        "token_counter",
    }
    scan_roots = [
        REPO_ROOT / "src",
        REPO_ROOT / "api",
        REPO_ROOT / "bot",
        REPO_ROOT / "main.py",
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
        resolved = path.resolve()
        if resolved in exempt_files:
            continue
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
        rel = path.relative_to(REPO_ROOT).as_posix()

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "litellm" or alias.name.startswith("litellm."):
                        violations.append(f"{rel}:{node.lineno}: direct import {alias.name}")
            elif isinstance(node, ast.ImportFrom):
                module_name = node.module or ""
                if module_name == "litellm" or module_name.startswith("litellm."):
                    violations.append(f"{rel}:{node.lineno}: direct from-import {module_name}")
            elif isinstance(node, ast.Call):
                func = node.func
                if (
                    isinstance(func, ast.Attribute)
                    and func.attr == "import_module"
                    and node.args
                    and isinstance(node.args[0], ast.Constant)
                    and isinstance(node.args[0].value, str)
                    and (
                        node.args[0].value == "litellm"
                        or node.args[0].value.startswith("litellm.")
                    )
                ):
                    violations.append(
                        f"{rel}:{node.lineno}: dynamic importlib.import_module({node.args[0].value!r})"
                    )
                elif (
                    isinstance(func, ast.Name)
                    and func.id == "__import__"
                    and node.args
                    and isinstance(node.args[0], ast.Constant)
                    and isinstance(node.args[0].value, str)
                    and (
                        node.args[0].value == "litellm"
                        or node.args[0].value.startswith("litellm.")
                    )
                ):
                    violations.append(f"{rel}:{node.lineno}: dynamic __import__({node.args[0].value!r})")
                elif (
                    isinstance(func, ast.Attribute)
                    and isinstance(func.value, ast.Name)
                    and func.value.id == "litellm"
                    and func.attr in forbidden_litellm_attrs
                ):
                    violations.append(f"{rel}:{node.lineno}: direct call litellm.{func.attr}()")
                elif (
                    isinstance(func, ast.Name)
                    and func.id == "Router"
                    and rel
                    in {
                        "src/analyzer.py",
                        "src/agent/llm_adapter.py",
                        "src/services/screening/ranker.py",
                    }
                ):
                    violations.append(f"{rel}:{node.lineno}: direct Router() call")

    assert violations == []


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
assert "litellm" not in sys.modules, f"litellm eagerly imported: {list(sys.modules.get('litellm').__dict__.keys())[:5]}"
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


def test_litellm_transport_strips_internal_api_surface_and_dispatches_cleanly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: List[Dict[str, Any]] = []
    router_cls = MagicMock(return_value="router-instance")

    def _fake_completion(**kwargs: Any) -> str:
        captured.append(dict(kwargs))
        return "ok"

    fake_litellm = SimpleNamespace(
        completion=_fake_completion,
        Router=router_cls,
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
        result = transport.completion(
            model="openai/gpt-5",
            messages=[{"role": "user", "content": "hi"}],
            api_surface="chat_completions",
            extra_headers={"X-Relay": "1"},
        )
        assert result == "ok"
        assert captured == [
            {
                "model": "openai/gpt-5",
                "messages": [{"role": "user", "content": "hi"}],
                "extra_headers": {"X-Relay": "1"},
            }
        ]

        created = transport.create_router(
            [{"model_name": "m", "litellm_params": {"model": "openai/m"}}],
            routing_strategy="simple-shuffle",
            num_retries=2,
        )
        assert created == "router-instance"
        router_cls.assert_called_once_with(
            model_list=[{"model_name": "m", "litellm_params": {"model": "openai/m"}}],
            routing_strategy="simple-shuffle",
            num_retries=2,
        )

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


def test_cjk_aware_token_estimation_fallback() -> None:
    """Token fallback preserves ceil(len/3) for ASCII and avoids CJK underestimation."""
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


def test_deployment_spec_normalization_and_env_resolution(monkeypatch: pytest.MonkeyPatch) -> None:
    """DeploymentSpec resolves os.environ/VAR centrally and preserves defaults with priority=0."""
    monkeypatch.setenv("TEST_RELAY_KEY", "sk-resolved-secret")
    monkeypatch.setenv("TEST_RELAY_BASE", "https://relay.example.com/v1")
    monkeypatch.setenv("TEST_AUTH_HEADER", "Bearer custom-token")

    raw_entry = {
        "model_name": "relay-gpt5",
        "litellm_params": {
            "model": "openai/gpt-5",
            "api_key": "os.environ/TEST_RELAY_KEY",
            "base_url": "os.environ/TEST_RELAY_BASE",
            "extra_headers": {
                "Authorization": "os.environ/TEST_AUTH_HEADER",
                "X-Tenant": "dsa",
            },
            "extra_body": {"reasoning_effort": "medium"},
            "temperature": 0.3,
            "max_tokens": 4096,
            "store": False,
            "timeout": "45.5",
        },
        "model_info": {
            "dsa_api_surface": "chat_completions",
            "dsa_channel_protocol": "openai",
        },
    }

    assert resolve_env_reference("os.environ/TEST_RELAY_KEY") == "sk-resolved-secret"
    resolved_params = resolve_litellm_params_env(raw_entry["litellm_params"])
    assert resolved_params["api_key"] == "sk-resolved-secret"
    assert resolved_params["extra_headers"]["Authorization"] == "Bearer custom-token"
    # Input dict is never mutated.
    assert raw_entry["litellm_params"]["api_key"] == "os.environ/TEST_RELAY_KEY"

    spec = normalize_deployment_spec(raw_entry)
    assert isinstance(spec, DeploymentSpec)
    assert spec.alias == "relay-gpt5"
    assert spec.wire_model == "openai/gpt-5"
    assert spec.protocol == "openai"
    assert spec.api_surface == "chat_completions"
    assert spec.api_base == "https://relay.example.com/v1"
    assert spec.api_key == "sk-resolved-secret"
    assert spec.extra_headers == {"Authorization": "Bearer custom-token", "X-Tenant": "dsa"}
    assert spec.extra_body == {"reasoning_effort": "medium"}
    assert spec.request_defaults == {"temperature": 0.3, "max_tokens": 4096, "store": False}
    assert spec.priority == 0
    assert spec.timeout == 45.5

    specs = normalize_deployment_specs([raw_entry, raw_entry])
    assert [item.priority for item in specs] == [0, 0]

    normalized_entries = normalize_model_list_entries([raw_entry])
    assert normalized_entries[0]["litellm_params"]["api_key"] == "sk-resolved-secret"
    assert normalized_entries[0]["model_info"]["dsa_api_surface"] == "chat_completions"


def test_ranker_yaml_resolves_env_refs_and_preserves_dsa_api_surface(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Screening ranker resolves os.environ/VAR in YAML litellm_params and preserves dsa_api_surface."""
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

    # Direct channel call preserves explicit chat_completions api_surface for OpenAI channels.
    fake2 = _RecordingTransport(response_text='{"ranked": []}')
    with use_transport(fake2):
        ranker._call_llm(
            "rank stocks",
            api_key="sk-channel",
            model="openai/gpt-5",
            base_url="",
            json_mode=False,
            channels=[
                {
                    "name": "relay",
                    "protocol": "openai",
                    "api_surface": "chat_completions",
                    "api_keys": ["sk-channel"],
                    "base_url": "https://relay.example/v1",
                    "models": ["openai/gpt-5"],
                }
            ],
        )
    assert fake2.completion_calls[0]["api_surface"] == "chat_completions"


def test_screening_header_proxy_prevents_cross_host_and_cross_key_leaks() -> None:
    """Screening header proxy never leaks relay credentials when api_base or api_key differs/is omitted."""
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
            # 1. Same model, omitted api_base (targets official host) -> MUST NOT inherit relay headers.
            dispatch_completion(model="openai/gpt-4o-mini", api_key="sk-relay-a", messages=[])
            # 2. Same model, omitted api_key -> MUST NOT inherit relay headers.
            dispatch_completion(
                model="openai/gpt-4o-mini",
                api_base="https://relay-a.example/v1",
                messages=[],
            )
            # 3. Same model, different host -> MUST NOT inherit relay headers.
            dispatch_completion(
                model="openai/gpt-4o-mini",
                api_key="sk-relay-a",
                api_base="https://other-host.example/v1",
                messages=[],
            )
            # 4. Exact host (ignoring trailing slash) + key match -> SHOULD inject headers.
            dispatch_completion(
                model="openai/gpt-4o-mini",
                api_key="sk-relay-a",
                api_base="https://relay-a.example/v1",
                messages=[],
            )
            # 5. Router entries: omitted api_base/api_key entry MUST NOT inherit relay headers.
            create_router(
                [
                    {
                        "model_name": "openai/gpt-4o-mini",
                        "litellm_params": {"model": "openai/gpt-4o-mini"},
                    },
                    {
                        "model_name": "openai/gpt-4o-mini",
                        "litellm_params": {
                            "model": "openai/gpt-4o-mini",
                            "api_key": "sk-relay-a",
                            "api_base": "https://relay-a.example/v1",
                        },
                    },
                ]
            )

    assert "extra_headers" not in fake.completion_calls[0]
    assert "extra_headers" not in fake.completion_calls[1]
    assert "extra_headers" not in fake.completion_calls[2]
    assert fake.completion_calls[3]["extra_headers"] == {
        "Authorization": "Bearer relay-a-secret",
        "X-Tenant": "relay-a",
    }

    router_entries = fake.router_calls[0]["model_list"]
    assert "extra_headers" not in router_entries[0]["litellm_params"]
    assert router_entries[1]["litellm_params"]["extra_headers"] == {
        "Authorization": "Bearer relay-a-secret",
        "X-Tenant": "relay-a",
    }

    # Official-host route (empty api_base) MUST NOT leak headers onto a custom api_base call.
    official_cfg = Config(
        litellm_model="gemini/gemini-2.5-flash",
        llm_model_list=[
            {
                "model_name": "gemini/gemini-2.5-flash",
                "litellm_params": {
                    "model": "gemini/gemini-2.5-flash",
                    "api_key": "sk-official-gemini",
                    "extra_headers": {"Authorization": "Bearer official-only"},
                },
            }
        ],
    )
    fake_official = _RecordingTransport(response_text="ok")
    with use_transport(fake_official):
        with screening_service._screening_litellm_headers(official_cfg):
            dispatch_completion(
                model="gemini/gemini-2.5-flash",
                api_key="sk-official-gemini",
                api_base="https://third-party-proxy.example/v1",
                messages=[],
            )
            dispatch_completion(
                model="gemini/gemini-2.5-flash",
                api_key="sk-official-gemini",
                messages=[],
            )
    assert "extra_headers" not in fake_official.completion_calls[0]
    assert fake_official.completion_calls[1]["extra_headers"] == {
        "Authorization": "Bearer official-only",
    }


def test_vision_extractor_honors_yaml_base_url_and_dsa_api_surface(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Vision extractor honors YAML base_url fallback and preserves dsa_api_surface."""
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


def test_config_persists_dsa_api_surface_for_both_surfaces_and_preserves_relay_models() -> None:
    """Config always persists dsa_api_surface on OpenAI channels and preserves opaque relay model IDs."""
    env = {
        "LLM_CHANNELS": "chat_relay,resp_relay,claude_direct",
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
    # Non-OpenAI channel carries protocol without falsely setting OpenAI dsa_api_surface.
    assert by_alias["anthropic/claude-sonnet-4-6"]["model_info"] == {
        "dsa_channel_protocol": "anthropic",
    }

    # Relay model normalization checks (opaque org/model + gateway vendor/model + compat).
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


def test_system_config_test_llm_channel_forwards_surface_headers_and_resets_cache() -> None:
    """test_llm_channel forwards api_surface & extra_headers through transport and reload resets cache."""
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

    # Error payload redacts sensitive Authorization header values.
    class _FailingTransport(_RecordingTransport):
        def completion(self, **kwargs: Any) -> Any:
            raise RuntimeError("Upstream rejected Bearer super-secret-hdr-9999")

    with use_transport(_FailingTransport()):
        err_payload = service.test_llm_channel(
            name="relay",
            protocol="openai",
            api_surface="chat_completions",
            base_url="https://relay.example/v1",
            api_key="sk-test-channel-key",
            models=["gpt-5"],
            extra_headers={"Authorization": "Bearer super-secret-hdr-9999"},
        )
    assert err_payload["success"] is False
    assert "super-secret-hdr-9999" not in str(err_payload)

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
